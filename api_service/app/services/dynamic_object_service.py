"""
Dynamic Object Service — business-logic layer for per-object Iceberg table management.

This service encapsulates:
  1. Trino connection utilities for dynamic table DDL operations
  2. Object-type-aware table creation (schema evolution ready)
  3. Table lifecycle management (create, list, describe, drop)
  4. Data ingestion orchestration (table bootstrap + record insert)
  5. Registry of known object types and their extended column schemas

Architecture:
  - Uses ``trino_config`` for low-level Trino connectivity (connection factory,
    context managers, health checks)
  - Uses ``iceberg_service`` for PyIceberg-based data writes (Arrow batches)
  - Exposes a clean service API consumed by the ``/api/v1/dynamic`` router

Object-type system:
  Every dynamic object has a ``object_type`` (e.g. "person", "robot", "vehicle").
  All types share the base dynamic schema (object_id, timestamp, pos/rot, speed,
  space_id, properties).  Certain types may have additional columns defined in
  ``OBJECT_TYPE_EXTRA_COLUMNS`` — these are appended at table creation time.
  The base schema always stays fixed so that Trino queries work uniformly.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import (
    DYNAMIC_TABLE_DDL,
    create_trino_connection,
    init_dynamic_table,
    init_namespace,
    list_dynamic_tables as _trino_list_dynamic_tables,
    trino_cursor,
)

# ═══════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════

# Regex for sanitising object IDs into valid Trino/Iceberg table names
_SAFE_ID_RE = re.compile(r"[^a-z0-9_]")

# Default catalog and namespace (from settings)
_CATALOG = property(lambda self: settings.trino_catalog)
_NAMESPACE = property(lambda self: settings.iceberg_namespace)


def _catalog() -> str:
    return settings.trino_catalog


def _namespace() -> str:
    return settings.iceberg_namespace


def _sanitize_id(object_id: str) -> str:
    """Sanitize an object ID for use as a Trino table name suffix."""
    return _SAFE_ID_RE.sub("_", object_id.lower().strip())


def _table_name(object_id: str) -> str:
    """Generate the dynamic table name for a given object_id."""
    return f"dynamic_{_sanitize_id(object_id)}"


def _fqtn(table_name: str, namespace: str | None = None) -> str:
    """Return fully-qualified table name: catalog.namespace.table."""
    ns = namespace or _namespace()
    return f"{_catalog()}.{ns}.{table_name}"


# ═══════════════════════════════════════════════════════════════════════
#  Object Type Registry — extended column definitions per type
# ═══════════════════════════════════════════════════════════════════════

# Each entry maps an object_type to a list of (column_name, trino_type) tuples.
# These columns are appended AFTER the base dynamic schema columns.
# The base schema is always: object_id, timestamp, pos_x/y/z, rot_x/y/z,
# speed, space_id, properties
OBJECT_TYPE_EXTRA_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "person": [
        ("tag_id", "VARCHAR"),
        ("activity_state", "VARCHAR"),       # e.g. "walking", "sitting", "running"
        ("confidence", "DOUBLE"),            # tracking confidence 0.0-1.0
    ],
    "robot": [
        ("battery_level", "DOUBLE"),         # 0.0-100.0
        ("task_id", "VARCHAR"),
        ("payload_weight", "DOUBLE"),        # kg
        ("operational_state", "VARCHAR"),     # e.g. "idle", "moving", "charging"
    ],
    "vehicle": [
        ("vehicle_type", "VARCHAR"),         # e.g. "forklift", "agv", "cart"
        ("heading", "DOUBLE"),               # degrees
        ("acceleration", "DOUBLE"),          # m/s²
        ("load_status", "VARCHAR"),          # e.g. "empty", "loaded"
    ],
    "sensor": [
        ("sensor_type", "VARCHAR"),          # e.g. "uwb", "lidar", "camera"
        ("reading_value", "DOUBLE"),
        ("reading_unit", "VARCHAR"),
        ("signal_strength", "DOUBLE"),       # dBm or normalized
    ],
    "asset": [
        ("asset_tag", "VARCHAR"),
        ("zone_transition", "VARCHAR"),      # previous_zone -> current_zone
        ("dwell_time_seconds", "DOUBLE"),
    ],
}

# Supported object types (base "generic" always available)
SUPPORTED_OBJECT_TYPES = {"generic"} | set(OBJECT_TYPE_EXTRA_COLUMNS.keys())


# ═══════════════════════════════════════════════════════════════════════
#  DDL Generation
# ═══════════════════════════════════════════════════════════════════════

def _build_create_table_ddl(
    table_name: str,
    object_type: str = "generic",
    namespace: str | None = None,
) -> str:
    """
    Build a CREATE TABLE IF NOT EXISTS DDL for a dynamic object table.

    The base schema matches DYNAMIC_TABLE_DDL from trino_config.
    If the object_type has extra columns in OBJECT_TYPE_EXTRA_COLUMNS,
    they are appended before the closing parenthesis.

    Parameters
    ----------
    table_name : str
        The table name (e.g. ``dynamic_person_01``).
    object_type : str
        The object type key (e.g. "person", "robot", "generic").
    namespace : str, optional
        Override namespace; defaults to settings.iceberg_namespace.
    """
    ns = namespace or _namespace()
    cat = _catalog()

    # Base columns (always present)
    base_columns = [
        "    object_id   VARCHAR NOT NULL",
        "    timestamp   TIMESTAMP(6) NOT NULL",
        "    pos_x       DOUBLE",
        "    pos_y       DOUBLE",
        "    pos_z       DOUBLE",
        "    rot_x       DOUBLE",
        "    rot_y       DOUBLE",
        "    rot_z       DOUBLE",
        "    speed       DOUBLE",
        "    space_id    VARCHAR",
        "    properties  VARCHAR",
        "    object_type VARCHAR",
    ]

    # Extra columns for the specific object type
    extra_cols = OBJECT_TYPE_EXTRA_COLUMNS.get(object_type, [])
    for col_name, col_type in extra_cols:
        base_columns.append(f"    {col_name:16s} {col_type}")

    columns_sql = ",\n".join(base_columns)

    # Partitioning strategy:
    #   - day(timestamp): daily partitions for efficient time-range queries
    #   - space_id: spatial partitions for per-zone congestion analysis
    # This enables Iceberg partition pruning on both temporal and spatial queries,
    # which are the two most common access patterns in digital twin scenarios.
    ddl = (
        f"CREATE TABLE IF NOT EXISTS {cat}.{ns}.{table_name} (\n"
        f"{columns_sql}\n"
        f")\n"
        f"WITH (\n"
        f"    format = 'PARQUET',\n"
        f"    partitioning = ARRAY['day(timestamp)', 'space_id']\n"
        f")"
    )
    return ddl


# ═══════════════════════════════════════════════════════════════════════
#  Table Creation Service
# ═══════════════════════════════════════════════════════════════════════

def create_dynamic_table(
    object_id: str,
    object_type: str = "generic",
    namespace: str | None = None,
) -> dict[str, Any]:
    """
    Create (or ensure) a per-object dynamic table in the Iceberg catalog.

    If ``object_type`` is "generic" or not in the registry, the base dynamic
    schema is used (compatible with ``trino_config.init_dynamic_table``).
    Otherwise, the type-specific extended schema is applied.

    Parameters
    ----------
    object_id : str
        Unique identifier for the dynamic object.
    object_type : str
        Object type key from SUPPORTED_OBJECT_TYPES.
    namespace : str, optional
        Override Iceberg namespace.

    Returns
    -------
    dict with keys: table_name, fqtn, object_type, created, columns
    """
    ns = namespace or _namespace()
    tbl = _table_name(object_id)
    fqtn = _fqtn(tbl, ns)

    # Ensure namespace exists
    init_namespace(ns)

    # Check if table already exists
    existing = list_tables(namespace=ns)
    already_exists = tbl in existing

    if already_exists:
        logger.info(
            "Dynamic table already exists: %s (object_type=%s)", fqtn, object_type
        )
        columns = describe_table(tbl, namespace=ns)
        return {
            "table_name": tbl,
            "fqtn": fqtn,
            "object_id": object_id,
            "object_type": object_type,
            "created": False,
            "columns": columns,
        }

    # For generic type, use the standard DDL from trino_config for consistency
    if object_type == "generic" or object_type not in OBJECT_TYPE_EXTRA_COLUMNS:
        effective_type = "generic"
        # Use the base DDL — but add the object_type column for future filtering
        ddl = _build_create_table_ddl(tbl, "generic", ns)
    else:
        effective_type = object_type
        ddl = _build_create_table_ddl(tbl, object_type, ns)

    # Execute DDL
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(ddl)
        cursor.fetchall()

    logger.info(
        "Created dynamic table: %s (object_type=%s)", fqtn, effective_type
    )

    columns = describe_table(tbl, namespace=ns)
    return {
        "table_name": tbl,
        "fqtn": fqtn,
        "object_id": object_id,
        "object_type": effective_type,
        "created": True,
        "columns": columns,
    }


def ensure_dynamic_table(
    object_id: str,
    object_type: str = "generic",
    namespace: str | None = None,
) -> str:
    """
    Ensure a dynamic table exists for the given object; return its FQTN.

    Convenience wrapper that returns only the fully-qualified table name.
    Suitable for use before data ingestion.
    """
    result = create_dynamic_table(object_id, object_type, namespace)
    return result["fqtn"]


# ═══════════════════════════════════════════════════════════════════════
#  Table Discovery & Introspection
# ═══════════════════════════════════════════════════════════════════════

def list_tables(namespace: str | None = None) -> list[str]:
    """
    List all dynamic_* table names in the Iceberg namespace via Trino.

    Delegates to ``trino_config.list_dynamic_tables`` for consistency.
    """
    return _trino_list_dynamic_tables(namespace=namespace)


def describe_table(
    table_name: str,
    namespace: str | None = None,
) -> list[dict[str, str]]:
    """
    Describe the columns of a dynamic table.

    Returns a list of dicts with 'column_name', 'data_type', 'is_nullable'.
    """
    ns = namespace or _namespace()
    fqtn = _fqtn(table_name, ns)

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(f"DESCRIBE {fqtn}")
        rows = cursor.fetchall()

    columns = []
    for row in rows:
        columns.append({
            "column_name": row[0],
            "data_type": row[1],
            "extra": row[2] if len(row) > 2 else "",
            "comment": row[3] if len(row) > 3 else "",
        })

    return columns


def table_exists(object_id: str, namespace: str | None = None) -> bool:
    """Check whether a dynamic table exists for the given object_id."""
    tbl = _table_name(object_id)
    existing = list_tables(namespace=namespace)
    return tbl in existing


def get_table_info(
    object_id: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    """
    Get detailed information about a dynamic object's table.

    Returns table metadata including columns, record count, and time range.
    """
    ns = namespace or _namespace()
    tbl = _table_name(object_id)
    fqtn = _fqtn(tbl, ns)

    if not table_exists(object_id, ns):
        return {
            "exists": False,
            "object_id": object_id,
            "table_name": tbl,
        }

    columns = describe_table(tbl, ns)

    # Fetch basic stats
    with trino_cursor(schema=ns) as cursor:
        try:
            cursor.execute(
                f"SELECT "
                f"  COUNT(*) AS record_count, "
                f"  MIN(timestamp) AS first_ts, "
                f"  MAX(timestamp) AS last_ts "
                f"FROM {fqtn}"
            )
            row = cursor.fetchone()
            record_count = row[0] if row else 0
            first_ts = row[1].isoformat() if row and row[1] else None
            last_ts = row[2].isoformat() if row and row[2] else None
        except Exception as e:
            logger.warning("Failed to get stats for %s: %s", fqtn, e)
            record_count = 0
            first_ts = None
            last_ts = None

    # Try to detect object_type from the object_type column
    detected_type = "generic"
    with trino_cursor(schema=ns) as cursor:
        try:
            cursor.execute(
                f"SELECT DISTINCT object_type FROM {fqtn} "
                f"WHERE object_type IS NOT NULL AND object_type != '' "
                f"LIMIT 5"
            )
            types = [r[0] for r in cursor.fetchall()]
            if types:
                detected_type = types[0]
        except Exception:
            # object_type column may not exist in older tables
            pass

    return {
        "exists": True,
        "object_id": object_id,
        "table_name": tbl,
        "fqtn": fqtn,
        "object_type": detected_type,
        "columns": columns,
        "record_count": record_count,
        "first_seen": first_ts,
        "last_seen": last_ts,
    }


def list_objects_with_info(namespace: str | None = None) -> list[dict[str, Any]]:
    """
    List all dynamic objects with enriched metadata.

    Returns a list of dicts with object_id, table_name, record_count,
    time range, and detected object_type.
    """
    tables = list_tables(namespace=namespace)
    ns = namespace or _namespace()

    if not tables:
        return []

    results = []
    conn = create_trino_connection(schema=ns)
    try:
        cursor = conn.cursor()
        for tbl in tables:
            # Derive object_id from table name
            obj_id = tbl[len("dynamic_"):]
            fqtn = _fqtn(tbl, ns)

            info: dict[str, Any] = {
                "object_id": obj_id,
                "table_name": tbl,
                "fqtn": fqtn,
                "record_count": 0,
                "first_seen": None,
                "last_seen": None,
                "object_type": "generic",
            }

            try:
                cursor.execute(
                    f"SELECT "
                    f"  COUNT(*) AS cnt, "
                    f"  MIN(timestamp) AS first_ts, "
                    f"  MAX(timestamp) AS last_ts "
                    f"FROM {fqtn}"
                )
                row = cursor.fetchone()
                if row:
                    info["record_count"] = row[0]
                    info["first_seen"] = row[1].isoformat() if row[1] else None
                    info["last_seen"] = row[2].isoformat() if row[2] else None
            except Exception as e:
                logger.warning("Failed to query stats for %s: %s", tbl, e)

            # Detect object_type
            try:
                cursor.execute(
                    f"SELECT DISTINCT object_type FROM {fqtn} "
                    f"WHERE object_type IS NOT NULL AND object_type != '' "
                    f"LIMIT 1"
                )
                type_rows = cursor.fetchall()
                if type_rows:
                    info["object_type"] = type_rows[0][0]
            except Exception:
                pass  # object_type column may not exist

            results.append(info)
    finally:
        conn.close()

    return results


# ═══════════════════════════════════════════════════════════════════════
#  Data Ingestion (orchestration)
# ═══════════════════════════════════════════════════════════════════════

def ingest_records(
    object_id: str,
    records: list[dict[str, Any]],
    object_type: str = "generic",
    namespace: str | None = None,
) -> dict[str, Any]:
    """
    Ingest dynamic object records with automatic table creation.

    Orchestrates:
      1. Ensure the per-object Iceberg table exists (with type-aware schema)
      2. Delegate data write to ``iceberg_service.insert_dynamic_records``
      3. Return ingestion summary

    Parameters
    ----------
    object_id : str
        The dynamic object identifier.
    records : list[dict]
        List of record dicts matching the dynamic schema.
    object_type : str
        Object type key for schema selection.
    namespace : str, optional
        Override namespace.

    Returns
    -------
    dict with inserted count, table name, and metadata.
    """
    from app.services import iceberg_service

    # Step 1: ensure table with type-appropriate schema via Trino DDL
    table_info = create_dynamic_table(object_id, object_type, namespace)

    # Step 2: inject object_type into each record for filtering
    for r in records:
        if "object_type" not in r or not r["object_type"]:
            r["object_type"] = object_type

    # Step 3: delegate data write via PyIceberg (Arrow batch)
    count, tbl_name = iceberg_service.insert_dynamic_records(object_id, records)

    logger.info(
        "Ingested %d records for object=%s type=%s table=%s",
        count, object_id, object_type, tbl_name,
    )

    return {
        "inserted": count,
        "table_name": tbl_name,
        "fqtn": table_info["fqtn"],
        "object_id": object_id,
        "object_type": object_type,
        "table_created": table_info["created"],
    }


# ═══════════════════════════════════════════════════════════════════════
#  Batch Table Creation (bootstrap multiple objects at once)
# ═══════════════════════════════════════════════════════════════════════

def batch_create_tables(
    objects: list[dict[str, str]],
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    """
    Create dynamic tables for multiple objects in one call.

    Parameters
    ----------
    objects : list[dict]
        Each dict must have ``object_id`` and optionally ``object_type``.
    namespace : str, optional
        Override namespace.

    Returns
    -------
    list of result dicts from ``create_dynamic_table``.
    """
    results = []
    for obj in objects:
        oid = obj["object_id"]
        otype = obj.get("object_type", "generic")
        try:
            result = create_dynamic_table(oid, otype, namespace)
            result["status"] = "ok"
        except Exception as e:
            logger.error("Failed to create table for %s: %s", oid, e)
            result = {
                "object_id": oid,
                "object_type": otype,
                "status": "error",
                "error": str(e),
            }
        results.append(result)

    logger.info("Batch table creation: %d requested, %d succeeded",
                len(objects), sum(1 for r in results if r.get("status") == "ok"))
    return results


# ═══════════════════════════════════════════════════════════════════════
#  Table Drop (cleanup)
# ═══════════════════════════════════════════════════════════════════════

def drop_dynamic_table(
    object_id: str,
    namespace: str | None = None,
) -> dict[str, Any]:
    """
    Drop a dynamic object's Iceberg table.

    Parameters
    ----------
    object_id : str
        The dynamic object whose table to drop.
    namespace : str, optional
        Override namespace.

    Returns
    -------
    dict with status and dropped table name.
    """
    ns = namespace or _namespace()
    tbl = _table_name(object_id)
    fqtn = _fqtn(tbl, ns)

    if not table_exists(object_id, ns):
        return {
            "status": "not_found",
            "object_id": object_id,
            "table_name": tbl,
            "message": f"Table {fqtn} does not exist",
        }

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(f"DROP TABLE IF EXISTS {fqtn}")
        cursor.fetchall()

    logger.info("Dropped dynamic table: %s", fqtn)
    return {
        "status": "ok",
        "object_id": object_id,
        "table_name": tbl,
        "fqtn": fqtn,
        "message": f"Table {fqtn} dropped successfully",
    }


# ═══════════════════════════════════════════════════════════════════════
#  Object Type Utilities
# ═══════════════════════════════════════════════════════════════════════

def get_supported_object_types() -> dict[str, Any]:
    """
    Return the registry of supported object types and their extra columns.

    Returns
    -------
    dict mapping type name to column definitions.
    """
    result = {"generic": {"extra_columns": [], "description": "Base dynamic schema only"}}
    for otype, cols in OBJECT_TYPE_EXTRA_COLUMNS.items():
        result[otype] = {
            "extra_columns": [
                {"name": name, "type": dtype} for name, dtype in cols
            ],
            "description": f"Dynamic object type: {otype}",
        }
    return result


def validate_object_type(object_type: str) -> bool:
    """Check if an object type is supported."""
    return object_type in SUPPORTED_OBJECT_TYPES
