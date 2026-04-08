"""
DynamicPrim IoT Streaming Router (Task 4).

Endpoints:
    POST   /api/v1/dynamic/register          — Register (create) a per-sensor Iceberg table
    POST   /api/v1/dynamic/ingest            — Batch ingest IoT records
    GET    /api/v1/dynamic/query/{table}     — Query sensor data with optional time range
    GET    /api/v1/dynamic/tables            — List all registered dynamic tables
    DELETE /api/v1/dynamic/{table}           — Drop a dynamic sensor table
    POST   /api/v1/dynamic/seed-demo         — Seed 24 h of demo data (~1 440 rows)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.logging import logger
from app.core.sql_utils import esc, validate_timestamp, validate_table_id
from app.core.trino_config import trino_cursor, init_namespace

from app.schemas.dynamic_prims import (
    DynamicIngestRequest,
    DynamicIngestResponse,
    DynamicQueryResponse,
    DynamicSeedDemoResponse,
    DynamicTableInfo,
    DynamicTableRegisterRequest,
    DynamicTableRegisterResponse,
    DynamicTablesListResponse,
)

router = APIRouter(prefix="/dynamic", tags=["dynamic-iot"])

# Catalog / namespace resolved from settings (same pattern as entities.py / raw_backup.py)
CATALOG = settings.trino_catalog
NAMESPACE = settings.iceberg_namespace

# In-memory registry: safe_table_name -> {prim_path, description}
# Survives for the lifetime of the process; in production this would be a metadata table.
_REGISTRY: dict[str, dict] = {}

# ═══════════════════════════════════════════════════════════════════════
#  DDL
# ═══════════════════════════════════════════════════════════════════════

DYNAMIC_SENSOR_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table_name} (
    capture_time  TIMESTAMP(6) WITH TIME ZONE,
    temperature   DOUBLE,
    humidity      DOUBLE,
    device_id     VARCHAR,
    quality_flag  VARCHAR,
    source_ip     VARCHAR,
    unit_temp     VARCHAR,
    unit_humid    VARCHAR
) WITH (
    partitioning = ARRAY['day(capture_time)'],
    sorted_by = ARRAY['capture_time']
)
"""


def _ensure_namespace() -> None:
    """Create the Iceberg namespace if it does not exist (idempotent)."""
    init_namespace(NAMESPACE)


def _create_sensor_table(safe_name: str) -> None:
    """Execute CREATE TABLE IF NOT EXISTS for a sensor table."""
    ddl = DYNAMIC_SENSOR_DDL.format(
        catalog=CATALOG,
        namespace=NAMESPACE,
        table_name=safe_name,
    )
    with trino_cursor(schema=NAMESPACE) as cursor:
        cursor.execute(ddl)
        cursor.fetchall()
    logger.info("Ensured dynamic table: %s.%s.%s", CATALOG, NAMESPACE, safe_name)


# ═══════════════════════════════════════════════════════════════════════
#  POST /dynamic/register
# ═══════════════════════════════════════════════════════════════════════

@router.post("/register", response_model=DynamicTableRegisterResponse)
async def register_dynamic_table(req: DynamicTableRegisterRequest):
    """Create a new per-sensor Iceberg table and register its metadata."""
    safe_name = validate_table_id(req.table_name)
    try:
        _ensure_namespace()
        _create_sensor_table(safe_name)
        _REGISTRY[safe_name] = {
            "prim_path": req.prim_path,
            "description": req.description,
        }
        logger.info("Registered dynamic table: %s", safe_name)
        return DynamicTableRegisterResponse(status="ok", table_name=safe_name)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("register_dynamic_table failed for %s: %s", safe_name, exc)
        return DynamicTableRegisterResponse(
            status="error",
            table_name=safe_name,
            error=str(exc),
        )


# ═══════════════════════════════════════════════════════════════════════
#  POST /dynamic/ingest
# ═══════════════════════════════════════════════════════════════════════

@router.post("/ingest", response_model=DynamicIngestResponse)
async def ingest_dynamic_data(req: DynamicIngestRequest):
    """Batch-insert IoT sensor records into the target dynamic table."""
    safe_name = validate_table_id(req.table_name)

    if not req.records:
        return DynamicIngestResponse(
            status="ok", records_inserted=0, table_name=safe_name
        )

    inserted = 0
    batch_size = 500

    try:
        with trino_cursor(schema=NAMESPACE) as cursor:
            for i in range(0, len(req.records), batch_size):
                batch = req.records[i : i + batch_size]
                values_list = []
                for r in batch:
                    # validate_timestamp returns "YYYY-MM-DD HH:MM:SS.ffffff"
                    # Append UTC suffix for TIMESTAMP WITH TIME ZONE column.
                    ct = validate_timestamp(r.capture_time)
                    values_list.append(
                        f"(TIMESTAMP '{ct} UTC', "
                        f"{r.temperature}, {r.humidity}, "
                        f"'{esc(r.device_id)}', '{esc(r.quality_flag)}', "
                        f"'{esc(r.source_ip)}', '{esc(r.unit_temp)}', "
                        f"'{esc(r.unit_humid)}')"
                    )
                sql = (
                    f"INSERT INTO {CATALOG}.{NAMESPACE}.{safe_name} "
                    f"(capture_time, temperature, humidity, device_id, "
                    f"quality_flag, source_ip, unit_temp, unit_humid) "
                    f"VALUES {', '.join(values_list)}"
                )
                try:
                    cursor.execute(sql)
                    cursor.fetchall()
                    inserted += len(batch)
                except Exception as exc:
                    logger.error(
                        "Batch ingest failed for %s (batch %d): %s",
                        safe_name, i // batch_size, exc,
                    )

        status = (
            "ok" if inserted == len(req.records)
            else ("partial" if inserted > 0 else "error")
        )
        return DynamicIngestResponse(
            status=status,
            records_inserted=inserted,
            table_name=safe_name,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("ingest_dynamic_data failed for %s: %s", safe_name, exc)
        return DynamicIngestResponse(
            status="error",
            records_inserted=inserted,
            table_name=safe_name,
            error=str(exc),
        )


# ═══════════════════════════════════════════════════════════════════════
#  GET /dynamic/query/{table_name}
# ═══════════════════════════════════════════════════════════════════════

@router.get("/query/{table_name}", response_model=DynamicQueryResponse)
async def query_dynamic_table(
    table_name: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=10000),
):
    """Query sensor data with optional time-range filter."""
    safe_name = validate_table_id(table_name)
    if safe_name not in _REGISTRY:
        raise HTTPException(status_code=404, detail=f"Dynamic table '{safe_name}' not registered")

    conditions = []
    if start_time:
        st = validate_timestamp(start_time)
        conditions.append(f"capture_time >= TIMESTAMP '{st} UTC'")
    if end_time:
        et = validate_timestamp(end_time)
        conditions.append(f"capture_time <= TIMESTAMP '{et} UTC'")

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT * FROM {CATALOG}.{NAMESPACE}.{safe_name}"
        f"{where} ORDER BY capture_time DESC LIMIT {limit}"
    )

    try:
        with trino_cursor(schema=NAMESPACE) as cursor:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            raw_rows = cursor.fetchall()

        rows = []
        for row in raw_rows:
            rec = {}
            for col, val in zip(columns, row):
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                rec[col] = val
            rows.append(rec)

        return DynamicQueryResponse(
            table_name=safe_name,
            columns=columns,
            rows=rows,
            total=len(rows),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("query_dynamic_table failed for %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════
#  GET /dynamic/tables
# ═══════════════════════════════════════════════════════════════════════

@router.get("/tables", response_model=DynamicTablesListResponse)
async def list_dynamic_tables():
    """List all dynamic sensor tables visible in Trino, merged with registry metadata."""
    try:
        with trino_cursor(schema=NAMESPACE) as cursor:
            cursor.execute(
                f"SELECT table_name FROM information_schema.tables "
                f"WHERE table_catalog = '{esc(CATALOG)}' "
                f"AND table_schema = '{esc(NAMESPACE)}'"
            )
            trino_tables = {row[0] for row in cursor.fetchall()}

        # Known system / non-dynamic tables to exclude
        _SYSTEM_TABLES = {
            "entities", "prim_snapshots", "raw_backup_files",
            "simulation_sessions", "simulation_deltas", "simulation_keyframes",
        }

        tables = []
        for tbl in sorted(trino_tables - _SYSTEM_TABLES):
            meta = _REGISTRY.get(tbl, {})
            tables.append(
                DynamicTableInfo(
                    table_name=tbl,
                    prim_path=meta.get("prim_path", ""),
                    description=meta.get("description", ""),
                )
            )

        return DynamicTablesListResponse(tables=tables)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("list_dynamic_tables failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════
#  DELETE /dynamic/{table_name}
# ═══════════════════════════════════════════════════════════════════════

@router.delete("/{table_name}")
async def delete_dynamic_table(table_name: str):
    """Drop a dynamic sensor table and remove it from the in-memory registry."""
    safe_name = validate_table_id(table_name)
    if safe_name not in _REGISTRY:
        raise HTTPException(status_code=404, detail=f"Dynamic table '{safe_name}' not registered")
    try:
        with trino_cursor(schema=NAMESPACE) as cursor:
            cursor.execute(
                f"DROP TABLE IF EXISTS {CATALOG}.{NAMESPACE}.{safe_name}"
            )
            cursor.fetchall()
        _REGISTRY.pop(safe_name, None)
        logger.info("Dropped dynamic table: %s", safe_name)
        return {"status": "ok", "table_name": safe_name}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("delete_dynamic_table failed for %s: %s", safe_name, exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════════
#  POST /dynamic/seed-demo
# ═══════════════════════════════════════════════════════════════════════

@router.post("/seed-demo", response_model=DynamicSeedDemoResponse)
async def seed_demo_data(table_name: str = "hum_temp_sensor1"):
    """Generate 24 h of demo IoT data at 1-minute intervals (~1 440 rows)."""
    safe_name = validate_table_id(table_name)

    try:
        _ensure_namespace()
        _create_sensor_table(safe_name)

        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(hours=24)

        # Build all 1 440 value tuples up-front
        records: list[str] = []
        for i in range(1440):
            t = start + timedelta(minutes=i)
            # Daily temperature cycle: cooler at night, warmer around noon
            hour_factor = abs(12 - t.hour) / 12.0
            temp = 22.0 + 6.0 * (1 - hour_factor) + random.uniform(-0.5, 0.5)
            humid = 55.0 - 10.0 * (1 - hour_factor) + random.uniform(-2.0, 2.0)
            quality = random.choices(
                ["good", "suspect", "bad"],
                weights=[94, 5, 1],
            )[0]
            ct = t.strftime("%Y-%m-%d %H:%M:%S.000000")
            records.append(
                f"(TIMESTAMP '{ct} UTC', "
                f"{temp:.4f}, {humid:.4f}, "
                f"'sensor-001', '{quality}', "
                f"'192.168.1.100', 'celsius', 'percent')"
            )

        inserted = 0
        batch_size = 500
        with trino_cursor(schema=NAMESPACE) as cursor:
            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]
                sql = (
                    f"INSERT INTO {CATALOG}.{NAMESPACE}.{safe_name} "
                    f"(capture_time, temperature, humidity, device_id, "
                    f"quality_flag, source_ip, unit_temp, unit_humid) "
                    f"VALUES {', '.join(batch)}"
                )
                try:
                    cursor.execute(sql)
                    cursor.fetchall()
                    inserted += len(batch)
                except Exception as exc:
                    logger.error(
                        "seed-demo batch %d failed for %s: %s",
                        i // batch_size, safe_name, exc,
                    )

        # Register in memory so the /tables listing shows metadata
        _REGISTRY[safe_name] = {
            "prim_path": f"/World/Dynamic/{table_name.replace('_', '-')}",
            "description": "Demo humidity/temperature sensor (24 h seeded data)",
        }

        time_range = f"{start.isoformat()} ~ {now.isoformat()}"
        status = (
            "ok" if inserted == 1440
            else ("partial" if inserted > 0 else "error")
        )
        logger.info(
            "seed-demo: inserted %d rows into %s (%s)",
            inserted, safe_name, time_range,
        )
        return DynamicSeedDemoResponse(
            status=status,
            table_name=safe_name,
            records_inserted=inserted,
            time_range=time_range,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("seed_demo_data failed for %s: %s", safe_name, exc)
        return DynamicSeedDemoResponse(
            status="error",
            table_name=safe_name,
            error=str(exc),
        )
