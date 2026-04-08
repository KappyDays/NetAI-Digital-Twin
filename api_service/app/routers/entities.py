"""
Entity-Level Backup/Restore/Diff + Simulation Router.

Endpoints:
    POST /api/v1/entities/backup             — Bulk insert entities + prim snapshots
    GET  /api/v1/entities/list               — List entities at a backup time
    GET  /api/v1/entities/diff               — Compare entities between two backup times
    GET  /api/v1/entities/backup-times       — List available backup timestamps
    GET  /api/v1/entities/{path}/prim-diff   — Compare sub-prims for an entity
    GET  /api/v1/entities/{path}/restore     — Get restore data for an entity
    GET  /api/v1/entities/restore-all        — Get ALL entities + prims at a backup time
    GET  /api/v1/entities/{path}/restore-prims — Selective prim restoration
    POST /api/v1/realtime/flush              — Flush simulation delta batch to Iceberg
    POST /api/v1/simulation/sessions         — Create simulation session
    PATCH /api/v1/simulation/sessions/{id}   — Update simulation session
    GET  /api/v1/simulation/sessions         — List simulation sessions
    GET  /api/v1/simulation/deltas           — Query simulation deltas (NDJSON)
    POST /api/v1/simulation/keyframes        — Store simulation keyframe
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.logging import logger
from app.core.sql_utils import esc, validate_timestamp
from app.core.trino_config import trino_cursor, init_namespace

from app.schemas.entities import (
    BackupTimesResponse,
    EntityBackupRequest,
    EntityBackupResponse,
    EntityDiffItem,
    EntityDiffResponse,
    EntityListResponse,
    EntityRestoreResponse,
    PrimDiffItem,
    PrimDiffResponse,
    SimulationSessionCreate,
    SimulationSessionUpdate,
    SimulationSessionResponse,
    SimulationKeyframeCreate,
)

router = APIRouter(tags=["Entity Backup"])

# Module-level flags to avoid repeated DDL on every request
_tables_ensured = False
_simulation_tables_ensured = False

# ═══════════════════════════════════════════════════════════════════════
#  Table Bootstrap
# ═══════════════════════════════════════════════════════════════════════

ENTITIES_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.entities (
    entity_id VARCHAR,
    entity_path VARCHAR,
    entity_type VARCHAR,
    source_type VARCHAR,
    source_asset VARCHAR,
    child_count INTEGER,
    entity_hash VARCHAR,
    usd_file_path VARCHAR,
    backup_source VARCHAR,
    depends_on VARCHAR,
    backup_time TIMESTAMP(6)
) WITH (
    partitioning = ARRAY['day(backup_time)']
)
"""

PRIM_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.prim_snapshots (
    entity_path VARCHAR,
    relative_path VARCHAR,
    prim_type VARCHAR,
    properties VARCHAR,
    prim_hash VARCHAR,
    backup_time TIMESTAMP(6)
) WITH (
    partitioning = ARRAY['day(backup_time)']
)
"""


def _get_table_columns(cursor, catalog: str, ns: str, table: str) -> list[str]:
    """Get existing column names for a table. Returns empty list if table doesn't exist."""
    try:
        cursor.execute(f"SHOW COLUMNS FROM {catalog}.{ns}.{table}")
        return [row[0] for row in cursor.fetchall()]
    except Exception:
        return []


# Expected columns per table — used for schema migration checks
_ENTITIES_EXPECTED_COLS = [
    "entity_id", "entity_path", "entity_type", "source_type", "source_asset",
    "child_count", "entity_hash", "usd_file_path",
    "backup_source", "depends_on", "backup_time",
]


def ensure_entity_tables() -> dict:
    """Create entities and prim_snapshots tables if they don't exist.

    Also checks for missing columns (schema drift from earlier versions)
    and recreates tables if needed. Uses a module-level flag to skip
    redundant checks after first success.
    """
    global _tables_ensured
    if _tables_ensured:
        return {"entities": "ok (cached)", "prim_snapshots": "ok (cached)"}

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    init_namespace(ns)

    results = {}
    with trino_cursor(schema=ns) as cursor:
        for name, ddl in [("entities", ENTITIES_DDL), ("prim_snapshots", PRIM_SNAPSHOTS_DDL)]:
            try:
                cursor.execute(ddl.format(catalog=catalog, namespace=ns))
                cursor.fetchall()
                results[name] = "ok"
                logger.info("Ensured table: %s.%s.%s", catalog, ns, name)
            except Exception as exc:
                results[name] = f"error: {exc}"
                logger.warning("Table creation issue for %s: %s", name, exc)

        # Schema migration: check if entities table has all expected columns
        existing_cols = _get_table_columns(cursor, catalog, ns, "entities")
        if existing_cols:
            missing = [c for c in _ENTITIES_EXPECTED_COLS if c not in existing_cols]
            if missing:
                logger.warning(
                    "entities table missing columns: %s — dropping and recreating",
                    missing,
                )
                try:
                    cursor.execute(f"DROP TABLE IF EXISTS {catalog}.{ns}.entities")
                    cursor.fetchall()
                    cursor.execute(ENTITIES_DDL.format(catalog=catalog, namespace=ns))
                    cursor.fetchall()
                    results["entities"] = "ok (recreated)"
                    logger.info("Recreated entities table with updated schema")
                except Exception as exc:
                    results["entities"] = f"error (migration): {exc}"
                    logger.error("Failed to recreate entities table: %s", exc)

    if all(v.startswith("ok") for v in results.values()):
        _tables_ensured = True

    return results


# ═══════════════════════════════════════════════════════════════════════
#  Simulation Tables Bootstrap
# ═══════════════════════════════════════════════════════════════════════

SIMULATION_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.simulation_sessions (
    simulation_id VARCHAR,
    scene_path VARCHAR,
    start_time TIMESTAMP(6) WITH TIME ZONE,
    end_time TIMESTAMP(6) WITH TIME ZONE,
    total_deltas BIGINT,
    entity_count INTEGER,
    status VARCHAR
)
"""

SIMULATION_DELTAS_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.simulation_deltas (
    capture_time TIMESTAMP(6) WITH TIME ZONE,
    simulation_id VARCHAR,
    entity_id VARCHAR,
    batch_id VARCHAR,
    prim_path VARCHAR,
    property_name VARCHAR,
    value_json VARCHAR,
    sequence_id BIGINT,
    sim_step BIGINT,
    sim_time_sec DOUBLE,
    delta_type VARCHAR,
    capture_source VARCHAR
)
"""

SIMULATION_KEYFRAMES_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.simulation_keyframes (
    keyframe_id VARCHAR,
    keyframe_time TIMESTAMP(6) WITH TIME ZONE,
    simulation_id VARCHAR,
    sim_step BIGINT,
    entity_id VARCHAR,
    full_state_json VARCHAR
)
"""


def ensure_simulation_tables():
    """Create simulation_sessions, simulation_deltas, simulation_keyframes tables if not exists."""
    global _simulation_tables_ensured
    if _simulation_tables_ensured:
        return

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    init_namespace(ns)

    all_ok = True
    with trino_cursor(schema=ns) as cursor:
        for name, ddl in [
            ("simulation_sessions", SIMULATION_SESSIONS_DDL),
            ("simulation_deltas", SIMULATION_DELTAS_DDL),
            ("simulation_keyframes", SIMULATION_KEYFRAMES_DDL),
        ]:
            try:
                cursor.execute(ddl.format(catalog=catalog, namespace=ns))
                cursor.fetchall()
                logger.info("Ensured table: %s.%s.%s", catalog, ns, name)
            except Exception as exc:
                logger.warning("%s table creation issue: %s", name, exc)
                all_ok = False

    if all_ok:
        _simulation_tables_ensured = True


# ═══════════════════════════════════════════════════════════════════════
#  POST /entities/backup
# ═══════════════════════════════════════════════════════════════════════

@router.post("/entities/backup", response_model=EntityBackupResponse)
async def backup_entities(req: EntityBackupRequest):
    """Bulk insert entity records and prim snapshots into Iceberg."""
    ensure_entity_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    backup_ts = validate_timestamp(req.backup_time)

    entities_inserted = 0
    prims_inserted = 0
    entity_error = ""
    prim_error = ""

    with trino_cursor(schema=ns) as cursor:
        # Batch insert entities (single INSERT with multiple VALUES rows)
        if req.entities:
            values_rows = []
            for e in req.entities:
                row = (
                    f"('{esc(e.entity_id)}', '{esc(e.entity_path)}', '{esc(e.entity_type)}', "
                    f"'{esc(e.source_type)}', '{esc(e.source_asset)}', "
                    f"{e.child_count}, '{esc(e.entity_hash)}', '{esc(e.usd_file_path)}', "
                    f"'{esc(req.backup_source)}', '{esc(e.depends_on)}', "
                    f"TIMESTAMP '{esc(backup_ts)}')"
                )
                values_rows.append(row)

            sql = (
                f"INSERT INTO {catalog}.{ns}.entities "
                f"(entity_id, entity_path, entity_type, source_type, source_asset, "
                f"child_count, entity_hash, usd_file_path, "
                f"backup_source, depends_on, backup_time) "
                f"VALUES {', '.join(values_rows)}"
            )
            try:
                cursor.execute(sql)
                cursor.fetchall()
                entities_inserted = len(req.entities)
            except Exception as exc:
                logger.error("Batch entity insert failed: %s", exc)
                entity_error = str(exc)

        # Batch insert prim snapshots
        if req.prim_snapshots:
            values_rows = []
            for p in req.prim_snapshots:
                row = (
                    f"('{esc(p.entity_path)}', '{esc(p.relative_path)}', '{esc(p.prim_type)}', "
                    f"'{esc(p.properties)}', '{esc(p.prim_hash)}', "
                    f"TIMESTAMP '{esc(backup_ts)}')"
                )
                values_rows.append(row)

            sql = (
                f"INSERT INTO {catalog}.{ns}.prim_snapshots "
                f"(entity_path, relative_path, prim_type, properties, prim_hash, backup_time) "
                f"VALUES {', '.join(values_rows)}"
            )
            try:
                cursor.execute(sql)
                cursor.fetchall()
                prims_inserted = len(req.prim_snapshots)
            except Exception as exc:
                logger.error("Batch prim snapshot insert failed: %s", exc)
                prim_error = str(exc)

    # Determine status based on insert results
    errors = []
    if entities_inserted == 0 and len(req.entities) > 0:
        errors.append(f"Entity insert failed: {entity_error}")
    if prims_inserted == 0 and len(req.prim_snapshots) > 0:
        errors.append(f"Prim insert failed: {prim_error}")

    status = "error" if errors else "ok"

    return EntityBackupResponse(
        status=status,
        entities_inserted=entities_inserted,
        prims_inserted=prims_inserted,
        backup_time=backup_ts,
        error="; ".join(errors) if errors else None,
    )


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/backup-times
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/backup-times", response_model=BackupTimesResponse)
async def get_backup_times():
    """Return distinct backup timestamps."""
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT backup_time, COALESCE(MAX(backup_source), 'extension') as src "
            f"FROM {catalog}.{ns}.entities "
            f"GROUP BY backup_time "
            f"ORDER BY backup_time DESC"
        )
        rows = cursor.fetchall()

    times = [row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]) for row in rows]
    sources = [row[1] if row[1] else "extension" for row in rows]
    return BackupTimesResponse(backup_times=times, backup_sources=sources)


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/list
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/list", response_model=EntityListResponse)
async def list_entities(backup_time: str = Query(..., description="Backup timestamp")):
    """List all entities at a specific backup time."""
    backup_time = validate_timestamp(backup_time)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"child_count, entity_hash, usd_file_path, depends_on, backup_time "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE backup_time = TIMESTAMP '{esc(backup_time)}' "
            f"ORDER BY entity_path"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    entities = []
    for row in rows:
        entity = {}
        for i, col in enumerate(cols):
            val = row[i]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            entity[col] = val
        entities.append(entity)

    return EntityListResponse(backup_time=backup_time, entities=entities)


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/diff
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/diff", response_model=EntityDiffResponse)
async def diff_entities(
    time_a: str = Query(..., description="First backup timestamp"),
    time_b: str = Query(..., description="Second backup timestamp"),
):
    """Compare entity hashes between two backup times."""
    time_a = validate_timestamp(time_a)
    time_b = validate_timestamp(time_b)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    def fetch_entities_at(ts: str) -> dict:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(
                f"SELECT entity_path, entity_hash, entity_type "
                f"FROM {catalog}.{ns}.entities "
                f"WHERE backup_time = TIMESTAMP '{esc(ts)}'"
            )
            return {row[0]: {"hash": row[1], "type": row[2]} for row in cursor.fetchall()}

    map_a = fetch_entities_at(time_a)
    map_b = fetch_entities_at(time_b)

    all_paths = set(map_a.keys()) | set(map_b.keys())
    items = []
    added = removed = changed = unchanged = 0

    for path in sorted(all_paths):
        in_a = path in map_a
        in_b = path in map_b

        if in_a and not in_b:
            items.append(EntityDiffItem(
                entity_path=path, status="removed",
                hash_a=map_a[path]["hash"], entity_type=map_a[path]["type"],
            ))
            removed += 1
        elif not in_a and in_b:
            items.append(EntityDiffItem(
                entity_path=path, status="added",
                hash_b=map_b[path]["hash"], entity_type=map_b[path]["type"],
            ))
            added += 1
        elif map_a[path]["hash"] != map_b[path]["hash"]:
            items.append(EntityDiffItem(
                entity_path=path, status="changed",
                hash_a=map_a[path]["hash"], hash_b=map_b[path]["hash"],
                entity_type=map_b[path]["type"],
            ))
            changed += 1
        else:
            items.append(EntityDiffItem(
                entity_path=path, status="unchanged",
                hash_a=map_a[path]["hash"], hash_b=map_b[path]["hash"],
                entity_type=map_b[path]["type"],
            ))
            unchanged += 1

    return EntityDiffResponse(
        time_a=time_a, time_b=time_b,
        total_a=len(map_a), total_b=len(map_b),
        added=added, removed=removed, changed=changed, unchanged=unchanged,
        entities=items,
    )


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/{entity_path}/prim-diff
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/{entity_path:path}/prim-diff", response_model=PrimDiffResponse)
async def prim_diff(
    entity_path: str,
    time_a: str = Query(...),
    time_b: str = Query(...),
):
    """Compare sub-prim hashes within an entity between two backup times."""
    time_a = validate_timestamp(time_a)
    time_b = validate_timestamp(time_b)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    def fetch_prims_at(ts: str) -> dict:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(
                f"SELECT relative_path, prim_type, prim_hash, properties "
                f"FROM {catalog}.{ns}.prim_snapshots "
                f"WHERE entity_path = '{esc(entity_path)}' "
                f"AND backup_time = TIMESTAMP '{esc(ts)}'"
            )
            return {
                row[0]: {"type": row[1], "hash": row[2], "properties": row[3]}
                for row in cursor.fetchall()
            }

    map_a = fetch_prims_at(time_a)
    map_b = fetch_prims_at(time_b)

    all_paths = set(map_a.keys()) | set(map_b.keys())
    items = []
    added = removed = changed = unchanged = 0

    for rel_path in sorted(all_paths):
        in_a = rel_path in map_a
        in_b = rel_path in map_b

        if in_a and not in_b:
            items.append(PrimDiffItem(
                relative_path=rel_path, status="removed",
                prim_type=map_a[rel_path]["type"],
                hash_a=map_a[rel_path]["hash"],
                properties_a=map_a[rel_path]["properties"],
            ))
            removed += 1
        elif not in_a and in_b:
            items.append(PrimDiffItem(
                relative_path=rel_path, status="added",
                prim_type=map_b[rel_path]["type"],
                hash_b=map_b[rel_path]["hash"],
                properties_b=map_b[rel_path]["properties"],
            ))
            added += 1
        elif map_a[rel_path]["hash"] != map_b[rel_path]["hash"]:
            items.append(PrimDiffItem(
                relative_path=rel_path, status="changed",
                prim_type=map_b[rel_path]["type"],
                hash_a=map_a[rel_path]["hash"], hash_b=map_b[rel_path]["hash"],
                properties_a=map_a[rel_path]["properties"],
                properties_b=map_b[rel_path]["properties"],
            ))
            changed += 1
        else:
            items.append(PrimDiffItem(
                relative_path=rel_path, status="unchanged",
                prim_type=map_b[rel_path]["type"],
                hash_a=map_a[rel_path]["hash"], hash_b=map_b[rel_path]["hash"],
            ))
            unchanged += 1

    return PrimDiffResponse(
        entity_path=entity_path, time_a=time_a, time_b=time_b,
        added=added, removed=removed, changed=changed, unchanged=unchanged,
        prims=items,
    )


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/restore-all
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/restore-all")
async def restore_all(
    backup_time: str = Query(..., description="Backup timestamp to restore from"),
):
    """Return ALL entities and ALL prim_snapshots at a given backup time.

    Used by the Time Travel Extension for Stage-wide restore in a single API call.
    """
    backup_time = validate_timestamp(backup_time)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    # 1. Fetch all entities at this backup time
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"child_count, entity_hash, usd_file_path, depends_on "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE backup_time = TIMESTAMP '{esc(backup_time)}'"
        )
        e_cols = [desc[0] for desc in cursor.description]
        e_rows = cursor.fetchall()

    entities = []
    for row in e_rows:
        entity = dict(zip(e_cols, row))
        for k, v in entity.items():
            if hasattr(v, "isoformat"):
                entity[k] = v.isoformat()
        entities.append(entity)

    # 2. Fetch all prim_snapshots at this backup time
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_path, relative_path, prim_type, properties, prim_hash "
            f"FROM {catalog}.{ns}.prim_snapshots "
            f"WHERE backup_time = TIMESTAMP '{esc(backup_time)}'"
        )
        p_cols = [desc[0] for desc in cursor.description]
        p_rows = cursor.fetchall()

    prim_snapshots = []
    for row in p_rows:
        snap = dict(zip(p_cols, row))
        prim_snapshots.append(snap)

    return {
        "backup_time": backup_time,
        "entity_count": len(entities),
        "prim_count": len(prim_snapshots),
        "entities": entities,
        "prim_snapshots": prim_snapshots,
    }


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/{entity_path}/restore-prims
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/{entity_path:path}/restore-prims")
async def restore_entity_prims(
    entity_path: str,
    backup_time: str = Query(...),
    relative_paths: str = Query(..., description="Comma-separated relative paths to restore"),
):
    """Get specific prim snapshots for partial entity restoration.

    Allows restoring only selected sub-prims (e.g., one Material from Looks)
    instead of the full entity prim list.
    """
    backup_time = validate_timestamp(backup_time)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    paths = [p.strip() for p in relative_paths.split(",") if p.strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="relative_paths must not be empty")

    paths_list = ", ".join(f"'{esc(p)}'" for p in paths)

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT relative_path, prim_type, properties, prim_hash "
            f"FROM {catalog}.{ns}.prim_snapshots "
            f"WHERE entity_path = '{esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{esc(backup_time)}' "
            f"AND relative_path IN ({paths_list}) "
            f"ORDER BY relative_path"
        )
        p_cols = [desc[0] for desc in cursor.description]
        p_rows = cursor.fetchall()

    prim_snapshots = [dict(zip(p_cols, row)) for row in p_rows]

    return {
        "entity_path": entity_path,
        "backup_time": backup_time,
        "requested_paths": paths,
        "prim_count": len(prim_snapshots),
        "prim_snapshots": prim_snapshots,
    }


# ═══════════════════════════════════════════════════════════════════════
#  GET /entities/{entity_path}/restore
# ═══════════════════════════════════════════════════════════════════════

@router.get("/entities/{entity_path:path}/restore", response_model=EntityRestoreResponse)
async def restore_entity(
    entity_path: str,
    backup_time: str = Query(...),
):
    """Get entity + sub-prim data for restoration."""
    backup_time = validate_timestamp(backup_time)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    # Fetch entity record
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"child_count, entity_hash, usd_file_path, depends_on "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE entity_path = '{esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{esc(backup_time)}'"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="Entity not found for the given path and backup time")

    entity = dict(zip(cols, rows[0]))
    for k, v in entity.items():
        if hasattr(v, "isoformat"):
            entity[k] = v.isoformat()

    # Fetch prim snapshots
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT relative_path, prim_type, properties, prim_hash "
            f"FROM {catalog}.{ns}.prim_snapshots "
            f"WHERE entity_path = '{esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{esc(backup_time)}' "
            f"ORDER BY relative_path"
        )
        p_cols = [desc[0] for desc in cursor.description]
        p_rows = cursor.fetchall()

    prim_snapshots = [dict(zip(p_cols, row)) for row in p_rows]

    return EntityRestoreResponse(
        entity_path=entity_path,
        backup_time=backup_time,
        entity=entity,
        prim_snapshots=prim_snapshots,
    )


# ═══════════════════════════════════════════════════════════════════════
#  POST /realtime/flush
# ═══════════════════════════════════════════════════════════════════════

_REALTIME_MAX_ITEMS = 50000


@router.post("/realtime/flush")
async def realtime_flush(request: Request, body: dict):
    """Flush a batch of simulation deltas into Iceberg.

    Requires simulation-specific fields (sequence_id, sim_step, sim_time_sec,
    delta_type, capture_source) to be present in at least one delta.
    Batches without simulation fields are ignored.
    """
    # Body-size enforcement: reject requests > 50 MB
    content_length = request.headers.get("content-length")
    _MAX_BODY_BYTES = 50 * 1024 * 1024  # 50 MB
    if content_length and int(content_length) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request body too large (max {_MAX_BODY_BYTES // (1024*1024)} MB)",
        )

    simulation_id = body.get("simulation_id", "")
    batch_id = body.get("batch_id", "")
    deltas = body.get("deltas", [])

    if not deltas:
        return {"status": "ok", "inserted": 0, "batch_id": batch_id, "simulation_id": simulation_id}

    if len(deltas) > _REALTIME_MAX_ITEMS:
        raise HTTPException(
            status_code=400,
            detail=f"deltas exceeds max_items limit ({_REALTIME_MAX_ITEMS})",
        )

    # Detect if this is a simulation flush (any sim-specific field present)
    _SIM_FIELDS = {"sequence_id", "sim_step", "sim_time_sec", "delta_type", "capture_source"}
    is_simulation = any(_SIM_FIELDS & set(d.keys()) for d in deltas)

    if not is_simulation:
        return {"status": "ok", "inserted": 0, "batch_id": batch_id, "simulation_id": simulation_id,
                "message": "non-simulation flush ignored"}

    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    # Validate and build value rows
    values_rows = []
    warnings = []
    for i, d in enumerate(deltas):
        # Validate value_json
        vj = d.get("value_json", "")
        try:
            json.loads(vj)
        except (json.JSONDecodeError, TypeError):
            warnings.append(f"delta[{i}]: invalid value_json, skipped")
            continue

        capture_time = validate_timestamp(str(d.get("capture_time", "")))

        seq_id = d.get("sequence_id")
        sim_step = d.get("sim_step")
        sim_time_sec = d.get("sim_time_sec")
        delta_type = d.get("delta_type", "")
        capture_source = d.get("capture_source", "")
        row = (
            f"(TIMESTAMP '{esc(capture_time)}', "
            f"'{esc(d.get('simulation_id', simulation_id))}', "
            f"'{esc(d.get('entity_id', ''))}', "
            f"'{esc(d.get('batch_id', batch_id))}', "
            f"'{esc(d.get('prim_path', ''))}', "
            f"'{esc(d.get('property_name', ''))}', "
            f"'{esc(vj)}', "
            f"{'NULL' if seq_id is None else int(seq_id)}, "
            f"{'NULL' if sim_step is None else int(sim_step)}, "
            f"{'NULL' if sim_time_sec is None else float(sim_time_sec)}, "
            f"'{esc(delta_type)}', "
            f"'{esc(capture_source)}')"
        )
        values_rows.append(row)

    if not values_rows:
        return {"status": "ok", "inserted": 0, "batch_id": batch_id, "simulation_id": simulation_id, "warnings": warnings}

    sql = (
        f"INSERT INTO {catalog}.{ns}.simulation_deltas "
        f"(capture_time, simulation_id, entity_id, batch_id, prim_path, property_name, value_json, "
        f"sequence_id, sim_step, sim_time_sec, delta_type, capture_source) "
        f"VALUES {', '.join(values_rows)}"
    )

    try:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(sql)
            cursor.fetchall()
    except Exception as exc:
        logger.error("Realtime flush INSERT failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Trino INSERT failed: {exc}")

    result = {
        "status": "ok",
        "inserted": len(values_rows),
        "batch_id": batch_id,
        "simulation_id": simulation_id,
        "table": "simulation_deltas",
    }
    if warnings:
        result["warnings"] = warnings
    return result


# ═══════════════════════════════════════════════════════════════════════
#  POST /simulation/sessions
# ═══════════════════════════════════════════════════════════════════════

@router.post("/simulation/sessions", response_model=SimulationSessionResponse)
async def create_simulation_session(req: SimulationSessionCreate):
    """Register a new simulation capture session."""
    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    now = datetime.now(timezone.utc)
    start_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")

    sql = (
        f"INSERT INTO {catalog}.{ns}.simulation_sessions "
        f"(simulation_id, scene_path, start_time, end_time, "
        f"total_deltas, entity_count, status) "
        f"VALUES ("
        f"'{esc(req.simulation_id)}', '{esc(req.scene_path)}', "
        f"TIMESTAMP '{esc(start_time)}', NULL, "
        f"0, {int(req.entity_count)}, 'running')"
    )

    try:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(sql)
            cursor.fetchall()
    except Exception as exc:
        logger.error("simulation_sessions INSERT failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Trino INSERT failed: {exc}")

    return SimulationSessionResponse(
        simulation_id=req.simulation_id,
        scene_path=req.scene_path,
        start_time=start_time,
        status="running",
    )


# ═══════════════════════════════════════════════════════════════════════
#  PATCH /simulation/sessions/{simulation_id}
# ═══════════════════════════════════════════════════════════════════════

@router.patch("/simulation/sessions/{simulation_id}")
async def update_simulation_session(simulation_id: str, req: SimulationSessionUpdate):
    """Update simulation session on completion (end_time, totals, status)."""
    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    set_clauses = []
    if req.end_time is not None:
        end_ts = validate_timestamp(req.end_time)
        set_clauses.append(f"end_time = TIMESTAMP '{esc(end_ts)}'")
    if req.total_deltas is not None:
        set_clauses.append(f"total_deltas = {int(req.total_deltas)}")
    if req.entity_count is not None:
        set_clauses.append(f"entity_count = {int(req.entity_count)}")
    if req.status is not None:
        set_clauses.append(f"status = '{esc(req.status)}'")

    if not set_clauses:
        return {"status": "ok", "updated": 0, "simulation_id": simulation_id}

    sql = (
        f"UPDATE {catalog}.{ns}.simulation_sessions "
        f"SET {', '.join(set_clauses)} "
        f"WHERE simulation_id = '{esc(simulation_id)}'"
    )

    try:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(sql)
            cursor.fetchall()
    except Exception as exc:
        logger.error("simulation_sessions UPDATE failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Trino UPDATE failed: {exc}")

    return {"status": "ok", "simulation_id": simulation_id}


# ═══════════════════════════════════════════════════════════════════════
#  GET /simulation/sessions
# ═══════════════════════════════════════════════════════════════════════

@router.get("/simulation/sessions")
async def list_simulation_sessions():
    """List recent simulation sessions ordered by start_time DESC."""
    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT simulation_id, scene_path, start_time, end_time, "
            f"total_deltas, entity_count, status "
            f"FROM {catalog}.{ns}.simulation_sessions "
            f"ORDER BY start_time DESC "
            f"LIMIT 50"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    sessions = []
    for row in rows:
        s = dict(zip(cols, row))
        for k, v in s.items():
            if hasattr(v, "isoformat"):
                s[k] = v.isoformat()
        sessions.append(s)

    return {"sessions": sessions, "count": len(sessions)}


# ═══════════════════════════════════════════════════════════════════════
#  GET /simulation/deltas
# ═══════════════════════════════════════════════════════════════════════

@router.get("/simulation/deltas")
async def get_simulation_deltas(
    simulation_id: str = Query(..., description="Simulation session ID"),
    start_time: str = Query(None, description="Filter start time (inclusive)"),
    end_time: str = Query(None, description="Filter end time (inclusive)"),
    limit: int = Query(default=10000, le=100000),
    offset: int = Query(default=0, ge=0),
    format: str = Query(default="json", description="Response format: json or ndjson"),
):
    """Fetch simulation deltas for replay. Ordered by sequence_id.

    format=ndjson returns newline-delimited JSON for streaming large datasets.
    """
    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    where = [f"simulation_id = '{esc(simulation_id)}'"]
    if start_time:
        st = validate_timestamp(start_time)
        where.append(f"capture_time >= TIMESTAMP '{esc(st)}'")
    if end_time:
        et = validate_timestamp(end_time)
        where.append(f"capture_time <= TIMESTAMP '{esc(et)}'")

    where_sql = " AND ".join(where)

    sql = (
        f"SELECT capture_time, simulation_id, entity_id, batch_id, prim_path, "
        f"property_name, value_json, sequence_id, sim_step, sim_time_sec, "
        f"delta_type, capture_source "
        f"FROM {catalog}.{ns}.simulation_deltas "
        f"WHERE {where_sql} "
        f"ORDER BY sequence_id "
        f"OFFSET {offset} LIMIT {limit}"
    )

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(sql)
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    def _row_to_dict(row):
        d = dict(zip(cols, row))
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    # NDJSON streaming response
    if format == "ndjson":
        def _generate_ndjson():
            for row in rows:
                yield json.dumps(_row_to_dict(row), default=str) + "\n"

        return StreamingResponse(
            _generate_ndjson(),
            media_type="application/x-ndjson",
        )

    # Standard JSON response
    deltas = [_row_to_dict(row) for row in rows]
    return {
        "simulation_id": simulation_id,
        "count": len(deltas),
        "offset": offset,
        "limit": limit,
        "deltas": deltas,
    }


# ═══════════════════════════════════════════════════════════════════════
#  POST /simulation/keyframes
# ═══════════════════════════════════════════════════════════════════════

@router.post("/simulation/keyframes")
async def create_simulation_keyframe(req: SimulationKeyframeCreate):
    """Store a full-state keyframe snapshot for a simulation step."""
    ensure_simulation_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    now = datetime.now(timezone.utc)
    keyframe_time = now.strftime("%Y-%m-%d %H:%M:%S.%f")

    # Validate full_state_json
    try:
        json.loads(req.full_state_json)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="full_state_json must be valid JSON")

    sql = (
        f"INSERT INTO {catalog}.{ns}.simulation_keyframes "
        f"(keyframe_id, keyframe_time, simulation_id, sim_step, entity_id, full_state_json) "
        f"VALUES ("
        f"'{esc(req.keyframe_id)}', TIMESTAMP '{esc(keyframe_time)}', "
        f"'{esc(req.simulation_id)}', {int(req.sim_step)}, "
        f"'{esc(req.entity_id)}', '{esc(req.full_state_json)}')"
    )

    try:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(sql)
            cursor.fetchall()
    except Exception as exc:
        logger.error("simulation_keyframes INSERT failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Trino INSERT failed: {exc}")

    return {
        "status": "ok",
        "keyframe_id": req.keyframe_id,
        "simulation_id": req.simulation_id,
        "keyframe_time": keyframe_time,
    }
