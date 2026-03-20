"""
Sensor data INSERT service via Trino SQL.

Inserts dynamic object IoT/sensor data into Iceberg tables through Trino,
complementing the PyIceberg-based ingestion in iceberg_service.py.

This Trino SQL path is preferred when:
  - Direct SQL INSERT is needed (e.g., from external ETL pipelines)
  - Schema validation should be enforced by Trino/Iceberg at write time
  - Batch INSERT optimization via multi-row VALUES is desired

Supports:
  - Single record INSERT
  - Batch INSERT (multi-row VALUES in a single statement)
  - Chunked batch INSERT for large payloads (configurable chunk size)
  - Auto table creation (DDL via trino_config.init_dynamic_table)

Architecture note:
  Dynamic objects each have their own Iceberg table (dynamic_<object_id>).
  The fixed schema supports schema evolution — new columns can be added
  later without breaking existing data or queries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import (
    init_dynamic_table,
    trino_cursor,
)

# ═══════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════

# Maximum rows per single INSERT statement to avoid Trino query size limits
DEFAULT_BATCH_CHUNK_SIZE = 500

# Column order must match DYNAMIC_TABLE_DDL in trino_config.py
DYNAMIC_COLUMNS = (
    "object_id",
    "timestamp",
    "pos_x",
    "pos_y",
    "pos_z",
    "rot_x",
    "rot_y",
    "rot_z",
    "speed",
    "space_id",
    "properties",
)


# ═══════════════════════════════════════════════════════════════════════
#  SQL Helpers
# ═══════════════════════════════════════════════════════════════════════

def _escape_sql_string(value: str) -> str:
    """Escape a string value for safe inclusion in a SQL literal."""
    return value.replace("'", "''").replace("\\", "\\\\")


def _format_timestamp(ts: datetime | str) -> str:
    """Format a timestamp for Trino TIMESTAMP literal."""
    if isinstance(ts, str):
        # Try to parse ISO format strings
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return ts.strftime("%Y-%m-%d %H:%M:%S.%f")


def _dynamic_table_name(object_id: str) -> str:
    """Generate the sanitised dynamic table name for an object."""
    safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
    return f"dynamic_{safe_id}"


def _fqtn(table_name: str) -> str:
    """Return fully-qualified table name: catalog.namespace.table."""
    return f"{settings.trino_catalog}.{settings.iceberg_namespace}.{table_name}"


def _record_to_values_tuple(record: dict[str, Any]) -> str:
    """
    Convert a sensor data record dict into a SQL VALUES tuple string.

    Example output:
        ('robot_01', TIMESTAMP '2024-01-01 00:00:00.000000', 1.0, 2.0, ...)
    """
    object_id = _escape_sql_string(str(record.get("object_id", "")))
    ts = record.get("timestamp", datetime.now(timezone.utc))
    ts_str = _format_timestamp(ts)
    pos_x = float(record.get("pos_x", 0.0))
    pos_y = float(record.get("pos_y", 0.0))
    pos_z = float(record.get("pos_z", 0.0))
    rot_x = float(record.get("rot_x", 0.0))
    rot_y = float(record.get("rot_y", 0.0))
    rot_z = float(record.get("rot_z", 0.0))
    speed = float(record.get("speed", 0.0))
    space_id = _escape_sql_string(str(record.get("space_id", "")))

    # Properties: ensure it's a JSON string
    props = record.get("properties", "{}")
    if isinstance(props, dict):
        props = json.dumps(props, ensure_ascii=False)
    props = _escape_sql_string(str(props))

    return (
        f"('{object_id}', "
        f"TIMESTAMP '{ts_str}', "
        f"{pos_x}, {pos_y}, {pos_z}, "
        f"{rot_x}, {rot_y}, {rot_z}, "
        f"{speed}, "
        f"'{space_id}', "
        f"'{props}')"
    )


def _build_insert_sql(fqtn: str, value_tuples: list[str]) -> str:
    """
    Build a multi-row INSERT INTO ... VALUES (...), (...) statement.

    Args:
        fqtn: Fully-qualified table name.
        value_tuples: List of formatted VALUES tuple strings.

    Returns:
        Complete INSERT SQL string.
    """
    columns_str = ", ".join(DYNAMIC_COLUMNS)
    values_str = ",\n    ".join(value_tuples)
    return (
        f"INSERT INTO {fqtn} ({columns_str})\n"
        f"VALUES\n    {values_str}"
    )


# ═══════════════════════════════════════════════════════════════════════
#  Single Record INSERT
# ═══════════════════════════════════════════════════════════════════════

def insert_single(
    record: dict[str, Any],
    *,
    ensure_table: bool = True,
) -> dict[str, Any]:
    """
    Insert a single sensor data record into the object's dynamic Iceberg table.

    Args:
        record: Dict with keys matching DYNAMIC_COLUMNS.
                Must contain at least 'object_id'.
        ensure_table: If True, create the table if it doesn't exist (DDL via Trino).

    Returns:
        Dict with inserted count, table name, and object_id.

    Raises:
        ValueError: If object_id is missing from the record.
        Exception: On Trino execution errors.
    """
    object_id = record.get("object_id")
    if not object_id:
        raise ValueError("record must contain 'object_id'")

    table_name = _dynamic_table_name(object_id)
    fqtn = _fqtn(table_name)

    # Ensure the table exists
    if ensure_table:
        init_dynamic_table(object_id)

    value_tuple = _record_to_values_tuple(record)
    sql = _build_insert_sql(fqtn, [value_tuple])

    with trino_cursor() as cursor:
        cursor.execute(sql)
        cursor.fetchall()  # consume result to complete execution

    logger.info(
        "Inserted 1 sensor record via Trino SQL: object=%s table=%s",
        object_id, table_name,
    )

    return {
        "inserted": 1,
        "table": table_name,
        "object_id": object_id,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Batch INSERT
# ═══════════════════════════════════════════════════════════════════════

def insert_batch(
    object_id: str,
    records: list[dict[str, Any]],
    *,
    chunk_size: int = DEFAULT_BATCH_CHUNK_SIZE,
    ensure_table: bool = True,
) -> dict[str, Any]:
    """
    Batch-insert multiple sensor data records for a single dynamic object.

    Records are grouped into chunks and each chunk is inserted as a single
    multi-row INSERT statement for efficiency.

    Args:
        object_id: The dynamic object identifier.
        records: List of record dicts. Each record's object_id field
                 is overwritten with the provided object_id for consistency.
        chunk_size: Max rows per INSERT statement (default 500).
        ensure_table: If True, auto-create the table before inserting.

    Returns:
        Dict with total inserted count, table name, object_id, and chunk count.

    Raises:
        ValueError: If records list is empty.
        Exception: On Trino execution errors (partial inserts may occur).
    """
    if not records:
        raise ValueError("records list must not be empty")

    table_name = _dynamic_table_name(object_id)
    fqtn = _fqtn(table_name)

    # Ensure the table exists
    if ensure_table:
        init_dynamic_table(object_id)

    # Normalize: ensure every record has the correct object_id
    for r in records:
        r["object_id"] = object_id

    # Split into chunks and execute
    total_inserted = 0
    chunk_count = 0

    for i in range(0, len(records), chunk_size):
        chunk = records[i : i + chunk_size]
        value_tuples = [_record_to_values_tuple(r) for r in chunk]
        sql = _build_insert_sql(fqtn, value_tuples)

        with trino_cursor() as cursor:
            cursor.execute(sql)
            cursor.fetchall()  # consume result

        total_inserted += len(chunk)
        chunk_count += 1
        logger.debug(
            "Inserted chunk %d (%d records) for object=%s",
            chunk_count, len(chunk), object_id,
        )

    logger.info(
        "Batch insert complete via Trino SQL: object=%s table=%s "
        "total=%d chunks=%d",
        object_id, table_name, total_inserted, chunk_count,
    )

    return {
        "inserted": total_inserted,
        "table": table_name,
        "object_id": object_id,
        "chunk_count": chunk_count,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Multi-Object Batch INSERT
# ═══════════════════════════════════════════════════════════════════════

def insert_multi_object_batch(
    records: list[dict[str, Any]],
    *,
    chunk_size: int = DEFAULT_BATCH_CHUNK_SIZE,
    ensure_table: bool = True,
) -> dict[str, Any]:
    """
    Insert sensor data records for multiple dynamic objects in one call.

    Records are grouped by object_id, then each group is batch-inserted
    into its respective per-object Iceberg table.

    Args:
        records: List of record dicts, each containing 'object_id'.
        chunk_size: Max rows per INSERT statement per object.
        ensure_table: If True, auto-create tables as needed.

    Returns:
        Dict with per-object results, total inserted count, and object count.

    Raises:
        ValueError: If records list is empty or any record lacks object_id.
    """
    if not records:
        raise ValueError("records list must not be empty")

    # Group records by object_id
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        oid = r.get("object_id")
        if not oid:
            raise ValueError("Every record must contain 'object_id'")
        grouped.setdefault(oid, []).append(r)

    results_per_object: list[dict[str, Any]] = []
    total_inserted = 0
    errors: list[dict[str, str]] = []

    for oid, obj_records in grouped.items():
        try:
            result = insert_batch(
                object_id=oid,
                records=obj_records,
                chunk_size=chunk_size,
                ensure_table=ensure_table,
            )
            results_per_object.append(result)
            total_inserted += result["inserted"]
        except Exception as exc:
            logger.error(
                "Failed to insert batch for object=%s: %s", oid, exc,
            )
            errors.append({"object_id": oid, "error": str(exc)})

    logger.info(
        "Multi-object batch insert: objects=%d total_inserted=%d errors=%d",
        len(grouped), total_inserted, len(errors),
    )

    return {
        "total_inserted": total_inserted,
        "object_count": len(grouped),
        "results": results_per_object,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Convenience Wrappers
# ═══════════════════════════════════════════════════════════════════════

def insert_sensor_reading(
    object_id: str,
    *,
    timestamp: Optional[datetime] = None,
    pos_x: float = 0.0,
    pos_y: float = 0.0,
    pos_z: float = 0.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    speed: float = 0.0,
    space_id: str = "",
    properties: str = "{}",
) -> dict[str, Any]:
    """
    Convenience function to insert a single sensor reading with keyword args.

    Wraps insert_single() for a cleaner API when constructing records inline.

    Args:
        object_id: Dynamic object identifier.
        timestamp: Reading timestamp (defaults to UTC now).
        pos_x, pos_y, pos_z: Position in world coordinates.
        rot_x, rot_y, rot_z: Rotation (euler degrees).
        speed: Speed in m/s.
        space_id: Current space/zone the object is in.
        properties: Extra properties as JSON string.

    Returns:
        Dict with inserted count, table name, and object_id.
    """
    record = {
        "object_id": object_id,
        "timestamp": timestamp or datetime.now(timezone.utc),
        "pos_x": pos_x,
        "pos_y": pos_y,
        "pos_z": pos_z,
        "rot_x": rot_x,
        "rot_y": rot_y,
        "rot_z": rot_z,
        "speed": speed,
        "space_id": space_id,
        "properties": properties,
    }
    return insert_single(record)


def get_insert_stats(object_id: str) -> dict[str, Any]:
    """
    Get basic statistics about inserted sensor data for a given object.

    Queries the object's dynamic table for record count, time range,
    and latest position — useful for verifying INSERT operations.

    Args:
        object_id: Dynamic object identifier.

    Returns:
        Dict with record_count, first/last timestamps, and latest position.
    """
    table_name = _dynamic_table_name(object_id)
    fqtn = _fqtn(table_name)

    sql = (
        f"SELECT "
        f"  COUNT(*) AS record_count, "
        f"  MIN(timestamp) AS first_timestamp, "
        f"  MAX(timestamp) AS last_timestamp "
        f"FROM {fqtn}"
    )

    with trino_cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()

    if not row or row[0] == 0:
        return {
            "object_id": object_id,
            "table_name": table_name,
            "record_count": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "latest_position": None,
        }

    # Get latest position
    pos_sql = (
        f"SELECT pos_x, pos_y, pos_z, speed, space_id "
        f"FROM {fqtn} "
        f"WHERE timestamp = (SELECT MAX(timestamp) FROM {fqtn}) "
        f"LIMIT 1"
    )

    with trino_cursor() as cursor:
        cursor.execute(pos_sql)
        pos_row = cursor.fetchone()

    latest_pos = None
    if pos_row:
        latest_pos = {
            "pos_x": pos_row[0],
            "pos_y": pos_row[1],
            "pos_z": pos_row[2],
            "speed": pos_row[3],
            "space_id": pos_row[4],
        }

    return {
        "object_id": object_id,
        "table_name": table_name,
        "record_count": row[0],
        "first_timestamp": row[1].isoformat() if row[1] else None,
        "last_timestamp": row[2].isoformat() if row[2] else None,
        "latest_position": latest_pos,
    }
