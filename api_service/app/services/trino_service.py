"""
Trino SQL query execution service.

Used for:
  - Ad-hoc queries on Iceberg tables
  - Congestion/visualization data aggregation
  - Dynamic object queries (time-range, spatial filter, trajectory)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import create_trino_connection


# ═══════════════════════════════════════════════════════════════════════
#  Connection
# ═══════════════════════════════════════════════════════════════════════

def get_trino_connection():
    """Create and return a Trino connection via centralized trino_config."""
    return create_trino_connection()


# ═══════════════════════════════════════════════════════════════════════
#  Generic query execution
# ═══════════════════════════════════════════════════════════════════════

def execute_query(sql: str) -> dict:
    """Execute a read-only SQL query via Trino and return results."""
    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        logger.info("Trino query returned %d rows", len(rows))
        return {
            "columns": columns,
            "rows": _serialize_rows(rows),
            "row_count": len(rows),
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
#  Dynamic Table Discovery
# ═══════════════════════════════════════════════════════════════════════

def _fqtn(table_name: str) -> str:
    """Return a fully-qualified table name: catalog.namespace.table."""
    return f"{settings.trino_catalog}.{settings.iceberg_namespace}.{table_name}"


def _dynamic_table_name(object_id: str) -> str:
    """Generate the dynamic table name for a given object_id."""
    safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
    return f"dynamic_{safe_id}"


def list_dynamic_tables() -> list[str]:
    """List all dynamic_* table names in the Iceberg namespace."""
    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        ns = settings.iceberg_namespace
        cursor.execute(
            f"SHOW TABLES FROM {settings.trino_catalog}.{ns} LIKE 'dynamic_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        logger.info("Found %d dynamic tables", len(tables))
        return tables
    finally:
        conn.close()


def list_dynamic_objects() -> list[dict]:
    """
    List all registered dynamic objects with basic metadata.

    Returns a list of dicts with object_id, table_name, and record_count.
    """
    tables = list_dynamic_tables()
    if not tables:
        return []

    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        results = []
        for tbl in tables:
            fqtn = _fqtn(tbl)
            # Extract object_id from table name (dynamic_<id>)
            obj_id = tbl[len("dynamic_"):]
            try:
                cursor.execute(
                    f"SELECT COUNT(*) AS cnt, MIN(timestamp) AS first_seen, "
                    f"MAX(timestamp) AS last_seen FROM {fqtn}"
                )
                row = cursor.fetchone()
                results.append({
                    "object_id": obj_id,
                    "table_name": tbl,
                    "record_count": row[0] if row else 0,
                    "first_seen": row[1].isoformat() if row and row[1] else None,
                    "last_seen": row[2].isoformat() if row and row[2] else None,
                })
            except Exception as e:
                logger.warning("Failed to query table %s: %s", tbl, e)
                results.append({
                    "object_id": obj_id,
                    "table_name": tbl,
                    "record_count": 0,
                    "first_seen": None,
                    "last_seen": None,
                })
        return results
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
#  Dynamic Object Queries — Core Utility Functions
# ═══════════════════════════════════════════════════════════════════════

def query_dynamic_by_time_range(
    object_id: str,
    start_time: datetime,
    end_time: datetime,
    limit: int = 10000,
    offset: int = 0,
    order: str = "ASC",
    speed_min: Optional[float] = None,
    speed_max: Optional[float] = None,
    space_id: Optional[str] = None,
) -> dict:
    """
    Query dynamic object records within a time range with pagination and filtering.

    Args:
        object_id: The dynamic object identifier.
        start_time: Start of the time window (inclusive).
        end_time: End of the time window (inclusive).
        limit: Maximum number of rows to return per page.
        offset: Number of rows to skip for pagination.
        order: Sort order for timestamp — "ASC" or "DESC".
        speed_min: Optional minimum speed filter (inclusive).
        speed_max: Optional maximum speed filter (inclusive).
        space_id: Optional space/zone filter.

    Returns:
        Dict with columns, rows (serialized), row_count, offset, limit, has_more.
    """
    tbl = _dynamic_table_name(object_id)
    fqtn = _fqtn(tbl)
    order = order.upper() if order.upper() in ("ASC", "DESC") else "ASC"

    where_clauses = [
        f"timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'",
        f"timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'",
    ]
    if speed_min is not None:
        where_clauses.append(f"speed >= {float(speed_min)}")
    if speed_max is not None:
        where_clauses.append(f"speed <= {float(speed_max)}")
    if space_id:
        where_clauses.append(f"space_id = '{_escape_sql(space_id)}'")
    where_sql = " AND ".join(where_clauses)

    # Fetch limit+1 rows to detect if more data exists beyond this page
    fetch_limit = int(limit) + 1

    sql = (
        f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
        f"rot_x, rot_y, rot_z, speed, space_id, properties "
        f"FROM {fqtn} "
        f"WHERE {where_sql} "
        f"ORDER BY timestamp {order} "
        f"OFFSET {int(offset)} "
        f"LIMIT {fetch_limit}"
    )
    logger.info(
        "Dynamic time-range query: object=%s [%s → %s] offset=%d limit=%d filters(speed=[%s,%s] space=%s)",
        object_id, start_time, end_time, offset, limit,
        speed_min, speed_max, space_id or "ALL",
    )
    result = execute_query(sql)

    # Determine pagination metadata
    has_more = len(result["rows"]) > limit
    if has_more:
        result["rows"] = result["rows"][:limit]
        result["row_count"] = limit

    result["offset"] = offset
    result["limit"] = limit
    result["has_more"] = has_more
    return result


def query_dynamic_by_space(
    space_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 10000,
    offset: int = 0,
    object_type: Optional[str] = None,
) -> dict:
    """
    Query all dynamic objects currently in (or historically passing through) a space.

    Searches across ALL dynamic_* tables for records matching the given space_id.
    Optionally filters by a time range and object_type.

    Args:
        space_id: The space/zone identifier to filter by.
        start_time: Optional start of time window (inclusive).
        end_time: Optional end of time window (inclusive).
        limit: Maximum total rows to return per page.
        offset: Number of rows to skip for pagination.
        object_type: Optional filter by object_type column.

    Returns:
        Dict with columns, rows, row_count, offset, limit, has_more.
    """
    tables = list_dynamic_tables()
    if not tables:
        return {"columns": [], "rows": [], "row_count": 0,
                "offset": offset, "limit": limit, "has_more": False}

    where_clauses = [f"space_id = '{_escape_sql(space_id)}'"]
    if start_time:
        where_clauses.append(
            f"timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    if end_time:
        where_clauses.append(
            f"timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    if object_type:
        where_clauses.append(f"object_type = '{_escape_sql(object_type)}'")
    where_sql = " AND ".join(where_clauses)

    union_parts = []
    for tbl in tables:
        fqtn = _fqtn(tbl)
        union_parts.append(
            f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
            f"rot_x, rot_y, rot_z, speed, space_id, properties "
            f"FROM {fqtn} WHERE {where_sql}"
        )

    fetch_limit = int(limit) + 1
    union_sql = " UNION ALL ".join(union_parts)
    sql = (
        f"SELECT * FROM ({union_sql}) AS combined "
        f"ORDER BY timestamp DESC "
        f"OFFSET {int(offset)} "
        f"LIMIT {fetch_limit}"
    )

    logger.info("Dynamic space query: space=%s tables=%d offset=%d limit=%d", space_id, len(tables), offset, limit)
    result = execute_query(sql)

    has_more = len(result["rows"]) > limit
    if has_more:
        result["rows"] = result["rows"][:limit]
        result["row_count"] = limit

    result["offset"] = offset
    result["limit"] = limit
    result["has_more"] = has_more
    return result


def query_dynamic_latest(
    object_id: Optional[str] = None,
) -> dict:
    """
    Get the latest record for a specific dynamic object or all dynamic objects.

    If object_id is provided, queries only that object's table.
    Otherwise, queries across ALL dynamic tables to return the latest record per object.

    Returns:
        Dict with columns, rows, and row_count.
    """
    if object_id:
        tbl = _dynamic_table_name(object_id)
        fqtn = _fqtn(tbl)
        sql = (
            f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
            f"rot_x, rot_y, rot_z, speed, space_id, properties "
            f"FROM {fqtn} "
            f"WHERE timestamp = (SELECT MAX(timestamp) FROM {fqtn}) "
            f"LIMIT 1"
        )
        logger.info("Dynamic latest query: object=%s", object_id)
        return execute_query(sql)

    # All objects — get latest record from each dynamic table
    tables = list_dynamic_tables()
    if not tables:
        return {"columns": [], "rows": [], "row_count": 0}

    union_parts = []
    for tbl in tables:
        fqtn = _fqtn(tbl)
        union_parts.append(
            f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
            f"rot_x, rot_y, rot_z, speed, space_id, properties "
            f"FROM {fqtn} "
            f"WHERE timestamp = (SELECT MAX(timestamp) FROM {fqtn})"
        )

    sql = " UNION ALL ".join(union_parts) + " ORDER BY object_id"
    logger.info("Dynamic latest-all query: tables=%d", len(tables))
    return execute_query(sql)


def query_dynamic_trajectory(
    object_id: str,
    start_time: datetime,
    end_time: datetime,
    sample_interval_seconds: Optional[int] = None,
    limit: int = 5000,
    offset: int = 0,
) -> dict:
    """
    Query the movement trajectory of a dynamic object over a time range.

    Returns position data (pos_x, pos_y, pos_z) ordered by time.
    Optionally downsamples by grouping into time buckets.

    Args:
        object_id: The dynamic object identifier.
        start_time: Start of the time window.
        end_time: End of the time window.
        sample_interval_seconds: If set, aggregate positions into N-second buckets.
        limit: Maximum number of trajectory points per page.
        offset: Number of rows to skip for pagination.

    Returns:
        Dict with columns, rows, row_count, offset, limit, has_more.
    """
    tbl = _dynamic_table_name(object_id)
    fqtn = _fqtn(tbl)
    fetch_limit = int(limit) + 1

    if sample_interval_seconds and sample_interval_seconds > 0:
        # Downsample: group timestamps into buckets and average positions
        sql = (
            f"SELECT "
            f"  object_id, "
            f"  date_trunc('second', timestamp) - "
            f"    (second(timestamp) % {int(sample_interval_seconds)}) * INTERVAL '1' SECOND AS time_bucket, "
            f"  AVG(pos_x) AS pos_x, AVG(pos_y) AS pos_y, AVG(pos_z) AS pos_z, "
            f"  AVG(speed) AS speed, "
            f"  COUNT(*) AS sample_count "
            f"FROM {fqtn} "
            f"WHERE timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}' "
            f"  AND timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}' "
            f"GROUP BY object_id, "
            f"  date_trunc('second', timestamp) - "
            f"    (second(timestamp) % {int(sample_interval_seconds)}) * INTERVAL '1' SECOND "
            f"ORDER BY time_bucket ASC "
            f"OFFSET {int(offset)} "
            f"LIMIT {fetch_limit}"
        )
    else:
        sql = (
            f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, speed, space_id "
            f"FROM {fqtn} "
            f"WHERE timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}' "
            f"  AND timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}' "
            f"ORDER BY timestamp ASC "
            f"OFFSET {int(offset)} "
            f"LIMIT {fetch_limit}"
        )

    logger.info(
        "Dynamic trajectory query: object=%s [%s → %s] sample=%s offset=%d limit=%d",
        object_id, start_time, end_time, sample_interval_seconds, offset, limit,
    )
    result = execute_query(sql)

    has_more = len(result["rows"]) > limit
    if has_more:
        result["rows"] = result["rows"][:limit]
        result["row_count"] = limit

    result["offset"] = offset
    result["limit"] = limit
    result["has_more"] = has_more
    return result


def query_dynamic_spatial_range(
    x_min: float, x_max: float,
    y_min: float, y_max: float,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 10000,
    offset: int = 0,
) -> dict:
    """
    Query dynamic objects within a spatial bounding box (coordinate range filter).

    Searches across ALL dynamic_* tables for records whose pos_x, pos_y, pos_z
    fall within the given bounds. Optionally filters by time range.

    Args:
        x_min, x_max: X-axis coordinate bounds.
        y_min, y_max: Y-axis coordinate bounds.
        z_min, z_max: Optional Z-axis coordinate bounds.
        start_time, end_time: Optional time range filter.
        limit: Maximum total rows per page.
        offset: Number of rows to skip for pagination.

    Returns:
        Dict with columns, rows, row_count, offset, limit, has_more.
    """
    tables = list_dynamic_tables()
    if not tables:
        return {"columns": [], "rows": [], "row_count": 0,
                "offset": offset, "limit": limit, "has_more": False}

    where_clauses = [
        f"pos_x >= {float(x_min)}", f"pos_x <= {float(x_max)}",
        f"pos_y >= {float(y_min)}", f"pos_y <= {float(y_max)}",
    ]
    if z_min is not None and z_max is not None:
        where_clauses.extend([
            f"pos_z >= {float(z_min)}", f"pos_z <= {float(z_max)}",
        ])
    if start_time:
        where_clauses.append(
            f"timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    if end_time:
        where_clauses.append(
            f"timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    where_sql = " AND ".join(where_clauses)

    union_parts = []
    for tbl in tables:
        fqtn = _fqtn(tbl)
        union_parts.append(
            f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
            f"rot_x, rot_y, rot_z, speed, space_id, properties "
            f"FROM {fqtn} WHERE {where_sql}"
        )

    fetch_limit = int(limit) + 1
    union_sql = " UNION ALL ".join(union_parts)
    sql = (
        f"SELECT * FROM ({union_sql}) AS combined "
        f"ORDER BY timestamp DESC "
        f"OFFSET {int(offset)} "
        f"LIMIT {fetch_limit}"
    )

    logger.info(
        "Dynamic spatial-range query: x=[%.2f,%.2f] y=[%.2f,%.2f] tables=%d offset=%d",
        x_min, x_max, y_min, y_max, len(tables), offset,
    )
    result = execute_query(sql)

    has_more = len(result["rows"]) > limit
    if has_more:
        result["rows"] = result["rows"][:limit]
        result["row_count"] = limit

    result["offset"] = offset
    result["limit"] = limit
    result["has_more"] = has_more
    return result


def query_space_congestion_timeseries(
    space_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    bucket_seconds: int = 60,
    limit: int = 1000,
) -> dict:
    """
    Compute congestion (object count) per time bucket for one or all spaces.

    Groups dynamic object records into time buckets and counts distinct
    objects per space_id in each bucket. Used for time-series congestion
    visualization on the dashboard.

    Args:
        space_id: Optional filter for a specific space.
        start_time, end_time: Optional time window.
        bucket_seconds: Size of each time bucket in seconds (default 60s).
        limit: Maximum result rows.

    Returns:
        Dict with columns, rows, and row_count.
    """
    tables = list_dynamic_tables()
    if not tables:
        return {"columns": [], "rows": [], "row_count": 0}

    where_clauses = ["space_id IS NOT NULL", "space_id != ''"]
    if space_id:
        where_clauses.append(f"space_id = '{_escape_sql(space_id)}'")
    if start_time:
        where_clauses.append(
            f"timestamp >= TIMESTAMP '{start_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    if end_time:
        where_clauses.append(
            f"timestamp <= TIMESTAMP '{end_time.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        )
    where_sql = " AND ".join(where_clauses)

    union_parts = []
    for tbl in tables:
        fqtn = _fqtn(tbl)
        union_parts.append(
            f"SELECT object_id, timestamp, space_id FROM {fqtn} WHERE {where_sql}"
        )

    union_sql = " UNION ALL ".join(union_parts)
    bucket_expr = (
        f"date_trunc('second', timestamp) - "
        f"(second(timestamp) % {int(bucket_seconds)}) * INTERVAL '1' SECOND"
    )

    sql = (
        f"SELECT "
        f"  space_id, "
        f"  {bucket_expr} AS time_bucket, "
        f"  COUNT(DISTINCT object_id) AS object_count "
        f"FROM ({union_sql}) AS combined "
        f"GROUP BY space_id, {bucket_expr} "
        f"ORDER BY time_bucket ASC, space_id "
        f"LIMIT {int(limit)}"
    )

    logger.info(
        "Congestion timeseries query: space=%s bucket=%ds tables=%d",
        space_id or "ALL", bucket_seconds, len(tables),
    )
    return execute_query(sql)


def get_space_congestion() -> dict:
    """
    Aggregate current congestion per space from the latest dynamic object positions.

    Query logic: For each dynamic_* table, get the latest record per object,
    then GROUP BY space_id to count objects per space.
    """
    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        ns = settings.iceberg_namespace

        # List all dynamic tables in the namespace
        cursor.execute(
            f"SHOW TABLES FROM {settings.trino_catalog}.{ns} LIKE 'dynamic_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            return {
                "spaces": [],
                "total_objects": 0,
                "snapshot_time": datetime.now(timezone.utc).isoformat(),
            }

        # Build a UNION ALL of latest records from each dynamic table
        union_parts = []
        for tbl in tables:
            union_parts.append(
                f"""
                SELECT object_id, space_id, timestamp
                FROM {settings.trino_catalog}.{ns}.{tbl}
                WHERE timestamp = (
                    SELECT MAX(timestamp) FROM {settings.trino_catalog}.{ns}.{tbl}
                )
                """
            )

        union_sql = " UNION ALL ".join(union_parts)
        agg_sql = f"""
            SELECT
                space_id,
                COUNT(DISTINCT object_id) AS object_count
            FROM ({union_sql}) t
            WHERE space_id IS NOT NULL AND space_id != ''
            GROUP BY space_id
            ORDER BY object_count DESC
        """

        cursor.execute(agg_sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]

        now = datetime.now(timezone.utc)
        total = sum(row[1] for row in rows)

        spaces = []
        for row in rows:
            space_id = row[0]
            count = row[1]
            # Normalized congestion (simple linear, can be refined with capacity)
            congestion = min(count / max(total, 1), 1.0)
            spaces.append({
                "space_id": space_id,
                "object_count": count,
                "congestion_level": round(congestion, 4),
                "timestamp": now.isoformat(),
            })

        return {
            "spaces": spaces,
            "total_objects": total,
            "snapshot_time": now.isoformat(),
        }
    finally:
        conn.close()


def get_congestion_grid(
    x_min: float = -50.0,
    x_max: float = 50.0,
    y_min: float = -50.0,
    y_max: float = 50.0,
    rows: int = 20,
    cols: int = 20,
) -> dict:
    """
    Compute a 2D congestion grid from the latest dynamic object positions.

    Divides the world space [x_min..x_max] x [y_min..y_max] into a rows x cols
    grid and counts objects in each cell based on their latest (pos_x, pos_y).

    Returns:
        Dict with grid config, cells (non-empty), full grid matrix, and metadata.
    """
    cell_width = (x_max - x_min) / cols
    cell_height = (y_max - y_min) / rows

    config = {
        "x_min": x_min, "x_max": x_max,
        "y_min": y_min, "y_max": y_max,
        "rows": rows, "cols": cols,
        "cell_width": round(cell_width, 6),
        "cell_height": round(cell_height, 6),
    }

    now = datetime.now(timezone.utc)

    # Get latest position of all dynamic objects
    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        ns = settings.iceberg_namespace

        cursor.execute(
            f"SHOW TABLES FROM {settings.trino_catalog}.{ns} LIKE 'dynamic_%'"
        )
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            grid = [[0.0] * cols for _ in range(rows)]
            return {
                "config": config,
                "cells": [],
                "grid": grid,
                "max_value": 0.0,
                "total_objects": 0,
                "snapshot_time": now.isoformat(),
            }

        # UNION ALL: latest record per dynamic table
        union_parts = []
        for tbl in tables:
            fqtn = f"{settings.trino_catalog}.{ns}.{tbl}"
            union_parts.append(
                f"SELECT object_id, pos_x, pos_y "
                f"FROM {fqtn} "
                f"WHERE timestamp = (SELECT MAX(timestamp) FROM {fqtn})"
            )

        union_sql = " UNION ALL ".join(union_parts)
        cursor.execute(union_sql)
        obj_rows = cursor.fetchall()

        # Build grid
        grid = [[0.0] * cols for _ in range(rows)]
        cell_objects: dict = {}  # (r, c) -> [object_ids]
        total_objects = 0

        for obj_row in obj_rows:
            obj_id, px, py = obj_row[0], float(obj_row[1]), float(obj_row[2])

            # Compute grid cell indices
            c = int((px - x_min) / cell_width)
            r = int((py - y_min) / cell_height)

            # Clamp to grid bounds
            c = max(0, min(c, cols - 1))
            r = max(0, min(r, rows - 1))

            grid[r][c] += 1.0
            cell_objects.setdefault((r, c), []).append(obj_id)
            total_objects += 1

        # Find max for normalization
        max_value = max(max(row_vals) for row_vals in grid) if total_objects > 0 else 0.0

        # Build non-empty cells list
        cells = []
        for (r, c), obj_ids in cell_objects.items():
            cells.append({
                "row": r,
                "col": c,
                "value": grid[r][c],
                "x_min": round(x_min + c * cell_width, 4),
                "x_max": round(x_min + (c + 1) * cell_width, 4),
                "y_min": round(y_min + r * cell_height, 4),
                "y_max": round(y_min + (r + 1) * cell_height, 4),
                "object_ids": obj_ids,
            })

        return {
            "config": config,
            "cells": cells,
            "grid": grid,
            "max_value": max_value,
            "total_objects": total_objects,
            "snapshot_time": now.isoformat(),
        }
    finally:
        conn.close()


def _serialize_rows(rows: list) -> list[list[Any]]:
    """Ensure all row values are JSON-serializable."""
    result = []
    for row in rows:
        serialized = []
        for val in row:
            if isinstance(val, datetime):
                serialized.append(val.isoformat())
            elif isinstance(val, bytes):
                serialized.append(val.decode("utf-8", errors="replace"))
            else:
                serialized.append(val)
        result.append(serialized)
    return result


def _escape_sql(value: str) -> str:
    """Basic SQL injection prevention for string literals."""
    return value.replace("'", "''").replace("\\", "\\\\").replace(";", "")


# ═══════════════════════════════════════════════════════════════════════
#  Static Object Queries — Core Utility Functions
# ═══════════════════════════════════════════════════════════════════════

def _static_fqtn() -> str:
    """Return the fully-qualified table name for the static prims table."""
    return _fqtn(settings.iceberg_table_name)


def query_static_all(
    limit: int = 10000,
    offset: int = 0,
) -> dict:
    """
    Retrieve all static Prim records from the Iceberg table.

    Args:
        limit: Maximum number of rows to return.
        offset: Number of rows to skip (for pagination).

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"ORDER BY prim_path ASC "
        f"OFFSET {int(offset)} "
        f"LIMIT {int(limit)}"
    )
    logger.info("Static all query: limit=%d offset=%d", limit, offset)
    return execute_query(sql)


def query_static_by_space(
    space_id: str,
    prim_type: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0,
) -> dict:
    """
    Query static Prim records belonging to a specific space.

    Space = each direct child of /World in the USD stage.
    Returns all Prim paths, types, and properties under that space.

    Args:
        space_id: The space identifier (e.g. "Room_A", "Hallway_01").
        prim_type: Optional filter by Prim type (e.g. "Mesh", "Xform").
        limit: Maximum number of rows to return.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    where_clauses = [f"space_id = '{_escape_sql(space_id)}'"]
    if prim_type:
        where_clauses.append(f"type = '{_escape_sql(prim_type)}'")
    where_sql = " AND ".join(where_clauses)

    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"WHERE {where_sql} "
        f"ORDER BY prim_path ASC "
        f"OFFSET {int(offset)} "
        f"LIMIT {int(limit)}"
    )
    logger.info("Static space query: space=%s type=%s offset=%d", space_id, prim_type or "ALL", offset)
    return execute_query(sql)


def query_static_by_prim_path(
    prim_path: str,
    exact: bool = True,
) -> dict:
    """
    Query static Prim record(s) by prim_path.

    Args:
        prim_path: Full or partial USD Prim path.
        exact: If True, match exact path. If False, use prefix matching
               (LIKE 'path%') to find the prim and all its descendants.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    if exact:
        where = f"prim_path = '{_escape_sql(prim_path)}'"
    else:
        # Prefix match: e.g. /World/Room_A% matches /World/Room_A and all children
        where = f"prim_path LIKE '{_escape_sql(prim_path)}%'"

    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"WHERE {where} "
        f"ORDER BY prim_path ASC "
        f"LIMIT 10000"
    )
    logger.info("Static prim_path query: path=%s exact=%s", prim_path, exact)
    return execute_query(sql)


def query_static_by_type(
    prim_type: str,
    space_id: Optional[str] = None,
    limit: int = 10000,
    offset: int = 0,
) -> dict:
    """
    Query static Prims filtered by their USD type name.

    Useful for finding all Meshes, Xforms, Lights, etc. in the scene
    or within a specific space.

    Args:
        prim_type: The Prim type name (e.g. "Mesh", "Xform", "DistantLight").
        space_id: Optional space filter to narrow results.
        limit: Maximum number of rows.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    where_clauses = [f"type = '{_escape_sql(prim_type)}'"]
    if space_id:
        where_clauses.append(f"space_id = '{_escape_sql(space_id)}'")
    where_sql = " AND ".join(where_clauses)

    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"WHERE {where_sql} "
        f"ORDER BY prim_path ASC "
        f"OFFSET {int(offset)} "
        f"LIMIT {int(limit)}"
    )
    logger.info("Static type query: type=%s space=%s offset=%d", prim_type, space_id or "ALL", offset)
    return execute_query(sql)


def list_static_spaces() -> dict:
    """
    List all distinct spaces (direct children of /World) in the static table.

    Returns aggregated info: space_id, prim_count, distinct type list,
    and latest ingestion timestamp per space.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    sql = (
        f"SELECT "
        f"  space_id, "
        f"  COUNT(*) AS prim_count, "
        f"  COUNT(DISTINCT type) AS type_count, "
        f"  MAX(ingested_at) AS last_ingested "
        f"FROM {fqtn} "
        f"WHERE space_id IS NOT NULL AND space_id != '' "
        f"GROUP BY space_id "
        f"ORDER BY prim_count DESC"
    )
    logger.info("Static spaces listing query")
    return execute_query(sql)


def query_static_type_summary(
    space_id: Optional[str] = None,
) -> dict:
    """
    Get a summary of Prim types and their counts.

    Optionally scoped to a specific space. Useful for understanding
    the composition of the scene or a zone.

    Args:
        space_id: Optional space filter.

    Returns:
        Dict with columns (type, count), rows, and row_count.
    """
    fqtn = _static_fqtn()
    where_clauses = []
    if space_id:
        where_clauses.append(f"space_id = '{_escape_sql(space_id)}'")

    where_sql = f"WHERE {' AND '.join(where_clauses)} " if where_clauses else ""

    sql = (
        f"SELECT "
        f"  type, "
        f"  COUNT(*) AS prim_count "
        f"FROM {fqtn} "
        f"{where_sql}"
        f"GROUP BY type "
        f"ORDER BY prim_count DESC"
    )
    logger.info("Static type summary query: space=%s", space_id or "ALL")
    return execute_query(sql)


def query_static_properties_search(
    search_key: str,
    search_value: Optional[str] = None,
    space_id: Optional[str] = None,
    limit: int = 10000,
) -> dict:
    """
    Search static Prims whose properties JSON contains a specific key or key-value.

    Uses Trino's json_extract_scalar for structured property search.
    Requires the properties column to be valid JSON.

    Args:
        search_key: JSON key to search for (e.g. "material", "visibility").
        search_value: Optional value to match for the given key.
        space_id: Optional space filter.
        limit: Maximum rows.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    safe_key = _escape_sql(search_key)

    where_clauses = [
        f"json_extract_scalar(properties, '$.{safe_key}') IS NOT NULL"
    ]
    if search_value is not None:
        where_clauses.append(
            f"json_extract_scalar(properties, '$.{safe_key}') = "
            f"'{_escape_sql(search_value)}'"
        )
    if space_id:
        where_clauses.append(f"space_id = '{_escape_sql(space_id)}'")
    where_sql = " AND ".join(where_clauses)

    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"WHERE {where_sql} "
        f"ORDER BY prim_path ASC "
        f"LIMIT {int(limit)}"
    )
    logger.info(
        "Static properties search: key=%s value=%s space=%s",
        search_key, search_value or "ANY", space_id or "ALL",
    )
    return execute_query(sql)


def query_static_count() -> dict:
    """
    Get the total count of static Prim records in the table.

    Returns:
        Dict with total_count and per-space breakdown.
    """
    fqtn = _static_fqtn()

    conn = get_trino_connection()
    try:
        cursor = conn.cursor()

        # Total count
        cursor.execute(f"SELECT COUNT(*) FROM {fqtn}")
        total_row = cursor.fetchone()
        total_count = total_row[0] if total_row else 0

        # Per-space breakdown
        cursor.execute(
            f"SELECT space_id, COUNT(*) AS cnt "
            f"FROM {fqtn} "
            f"WHERE space_id IS NOT NULL AND space_id != '' "
            f"GROUP BY space_id "
            f"ORDER BY cnt DESC"
        )
        space_rows = cursor.fetchall()
        space_counts = {row[0]: row[1] for row in space_rows}

        logger.info("Static count query: total=%d spaces=%d", total_count, len(space_counts))
        return {
            "total_count": total_count,
            "space_counts": space_counts,
            "space_count": len(space_counts),
        }
    finally:
        conn.close()


def query_static_hierarchy(
    root_path: str = "/World",
    max_depth: Optional[int] = None,
) -> dict:
    """
    Query static Prims as a hierarchical tree rooted at root_path.

    Returns prim records filtered by path prefix, with an additional
    computed 'depth' column indicating hierarchy level.

    Args:
        root_path: Root prim path (default /World).
        max_depth: Optional maximum depth relative to root. None = unlimited.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    safe_root = _escape_sql(root_path.rstrip("/"))
    root_depth = safe_root.count("/")

    where_clauses = [f"prim_path LIKE '{safe_root}/%'"]
    if max_depth is not None:
        # depth = number of '/' in prim_path - number of '/' in root
        # e.g., root=/World (depth 1), /World/Room/Mesh = depth 3, relative = 2
        abs_max = root_depth + int(max_depth)
        where_clauses.append(
            f"cardinality(split(prim_path, '/')) - 1 <= {abs_max}"
        )
    where_sql = " AND ".join(where_clauses)

    sql = (
        f"SELECT "
        f"  prim_path, type, properties, space_id, ingested_at, "
        f"  cardinality(split(prim_path, '/')) - 1 - {root_depth} AS depth "
        f"FROM {fqtn} "
        f"WHERE {where_sql} "
        f"ORDER BY prim_path ASC "
        f"LIMIT 50000"
    )
    logger.info("Static hierarchy query: root=%s max_depth=%s", root_path, max_depth)
    return execute_query(sql)


def query_space_drilldown(space_id: str) -> dict:
    """
    Retrieve full drill-down data for a single space.

    Combines static Prims (from Iceberg static table) and dynamic objects
    (latest state from per-object dynamic tables) for object-level detail.

    Returns:
        Dict with static_objects, dynamic_objects, type_distribution,
        last_static_ingestion, and summary counts.
    """
    import json as _json

    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        now = datetime.now(timezone.utc)
        safe_space = _escape_sql(space_id)
        fqtn = _static_fqtn()

        # ── 1. Static objects in this space ─────────────────────────────
        cursor.execute(
            f"SELECT prim_path, type, properties, space_id, ingested_at "
            f"FROM {fqtn} "
            f"WHERE space_id = '{safe_space}' "
            f"ORDER BY prim_path ASC "
            f"LIMIT 50000"
        )
        static_rows = cursor.fetchall()

        type_dist: dict[str, int] = {}
        static_objects = []
        last_ingestion = None
        space_root_depth = 2  # /World/<SpaceId> = depth 2

        for row in static_rows:
            prim_path = row[0]
            obj_type = row[1]
            props_str = row[2] or "{}"
            ingested = row[4]

            type_dist[obj_type] = type_dist.get(obj_type, 0) + 1

            if ingested:
                ts_str = ingested.isoformat() if hasattr(ingested, "isoformat") else str(ingested)
                if last_ingestion is None or ts_str > last_ingestion:
                    last_ingestion = ts_str

            try:
                props = _json.loads(props_str)
            except (ValueError, TypeError):
                props = {}

            transform = props.get("transform", {})
            translate = transform.get("translate", {})
            rotate = transform.get("rotate", {})
            scale = transform.get("scale", {})
            metadata = props.get("metadata", {})
            parent_path = props.get("parent_path")
            child_count = props.get("child_count", 0)
            depth = max(prim_path.count("/") - space_root_depth, 0)

            static_objects.append({
                "prim_path": prim_path,
                "object_type": obj_type,
                "parent_path": parent_path,
                "position": {"x": translate.get("x", 0), "y": translate.get("y", 0), "z": translate.get("z", 0)} if translate else None,
                "rotation": {"x": rotate.get("x", 0), "y": rotate.get("y", 0), "z": rotate.get("z", 0)} if rotate else None,
                "scale": {"x": scale.get("x", 1), "y": scale.get("y", 1), "z": scale.get("z", 1)} if scale else None,
                "visibility": metadata.get("visibility"),
                "material_path": metadata.get("material_path"),
                "semantic_label": metadata.get("semantic_label"),
                "child_count": child_count,
                "depth": depth,
                "properties_raw": props_str,
            })

        # ── 2. Dynamic objects in this space (latest per object) ────────
        ns = settings.iceberg_namespace
        try:
            cursor.execute(
                f"SHOW TABLES FROM {settings.trino_catalog}.{ns} LIKE 'dynamic_%'"
            )
            dyn_tables = [r[0] for r in cursor.fetchall()]
        except Exception:
            dyn_tables = []

        dynamic_objects = []
        if dyn_tables:
            union_parts = []
            for tbl in dyn_tables:
                fq = f"{settings.trino_catalog}.{ns}.{tbl}"
                union_parts.append(
                    f"SELECT object_id, timestamp, pos_x, pos_y, pos_z, "
                    f"rot_x, rot_y, rot_z, speed, space_id, properties "
                    f"FROM {fq} "
                    f"WHERE space_id = '{safe_space}' "
                    f"AND timestamp = ("
                    f"  SELECT MAX(timestamp) FROM {fq} "
                    f"  WHERE space_id = '{safe_space}'"
                    f")"
                )
            union_sql = " UNION ALL ".join(union_parts)
            try:
                cursor.execute(union_sql)
                dyn_rows = cursor.fetchall()
                for drow in dyn_rows:
                    ts = drow[1]
                    status = "unknown"
                    if ts:
                        ts_dt = ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))
                        age_seconds = (now - ts_dt).total_seconds()
                        if age_seconds < 60:
                            status = "active"
                        elif age_seconds < 300:
                            status = "idle"
                        else:
                            status = "stale"

                    dynamic_objects.append({
                        "object_id": drow[0],
                        "position": {"x": float(drow[2] or 0), "y": float(drow[3] or 0), "z": float(drow[4] or 0)},
                        "rotation": {"x": float(drow[5] or 0), "y": float(drow[6] or 0), "z": float(drow[7] or 0)},
                        "speed": float(drow[8] or 0),
                        "space_id": drow[9] or "",
                        "last_seen": ts.isoformat() if hasattr(ts, "isoformat") else str(ts) if ts else None,
                        "status": status,
                        "properties": drow[10] or "{}",
                    })
            except Exception as e:
                logger.warning("Dynamic drilldown query failed: %s", e)

        logger.info(
            "Space drilldown: space=%s static=%d dynamic=%d types=%d",
            space_id, len(static_objects), len(dynamic_objects), len(type_dist),
        )
        return {
            "space_id": space_id,
            "static_count": len(static_objects),
            "dynamic_count": len(dynamic_objects),
            "type_distribution": type_dist,
            "static_objects": static_objects,
            "dynamic_objects": dynamic_objects,
            "last_static_ingestion": last_ingestion,
            "snapshot_time": now.isoformat(),
        }
    finally:
        conn.close()


def query_static_latest_ingestion() -> dict:
    """
    Get the latest ingestion batch — all records sharing the MAX(ingested_at) timestamp.

    Useful for verifying the most recent Isaac Sim → Lakehouse sync.

    Returns:
        Dict with columns, rows (serialized), and row_count.
    """
    fqtn = _static_fqtn()
    sql = (
        f"SELECT prim_path, type, properties, space_id, ingested_at "
        f"FROM {fqtn} "
        f"WHERE ingested_at = (SELECT MAX(ingested_at) FROM {fqtn}) "
        f"ORDER BY prim_path ASC"
    )
    logger.info("Static latest-ingestion query")
    return execute_query(sql)
