"""
Entity-Level 3-Level Backup/Restore/Diff Router.

Endpoints:
    POST /api/v1/entities/backup        — Bulk insert entities + prim snapshots
    GET  /api/v1/entities/list           — List entities at a backup time
    GET  /api/v1/entities/diff           — Compare entities between two backup times
    GET  /api/v1/entities/backup-times   — List available backup timestamps
    GET  /api/v1/entities/{path}/prim-diff   — Compare sub-prims for an entity
    GET  /api/v1/entities/{path}/restore     — Get restore data for an entity
    GET  /api/v1/entities/restore-all    — Get ALL entities + prims at a backup time
    POST /api/v1/dynamic/sample-ingest   — Generate sample IoT data
"""

from __future__ import annotations

import re
import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.logging import logger
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
    SampleIoTRequest,
    SampleIoTResponse,
)

router = APIRouter(tags=["Entity Backup"])

# Module-level flag to avoid repeated DDL on every request
_tables_ensured = False

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
    is_dynamic BOOLEAN,
    dynamic_table VARCHAR,
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


def ensure_entity_tables() -> dict:
    """Create entities and prim_snapshots tables if they don't exist.

    Uses a module-level flag to skip redundant DDL after first success.
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

    if all(v == "ok" for v in results.values()):
        _tables_ensured = True

    return results


# ═══════════════════════════════════════════════════════════════════════
#  POST /entities/backup
# ═══════════════════════════════════════════════════════════════════════

@router.post("/entities/backup", response_model=EntityBackupResponse)
async def backup_entities(req: EntityBackupRequest):
    """Bulk insert entity records and prim snapshots into Iceberg."""
    ensure_entity_tables()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    backup_ts = _validate_timestamp(req.backup_time)

    entities_inserted = 0
    prims_inserted = 0

    with trino_cursor(schema=ns) as cursor:
        # Batch insert entities (single INSERT with multiple VALUES rows)
        if req.entities:
            values_rows = []
            for e in req.entities:
                row = (
                    f"('{_esc(e.entity_id)}', '{_esc(e.entity_path)}', '{_esc(e.entity_type)}', "
                    f"'{_esc(e.source_type)}', '{_esc(e.source_asset)}', "
                    f"{str(e.is_dynamic).lower()}, '{_esc(e.dynamic_table)}', "
                    f"{e.child_count}, '{_esc(e.entity_hash)}', '{_esc(e.usd_file_path)}', "
                    f"'{_esc(req.backup_source)}', '{_esc(e.depends_on)}', "
                    f"TIMESTAMP '{_esc(backup_ts)}')"
                )
                values_rows.append(row)

            sql = (
                f"INSERT INTO {catalog}.{ns}.entities "
                f"(entity_id, entity_path, entity_type, source_type, source_asset, "
                f"is_dynamic, dynamic_table, child_count, entity_hash, usd_file_path, "
                f"backup_source, depends_on, backup_time) "
                f"VALUES {', '.join(values_rows)}"
            )
            try:
                cursor.execute(sql)
                cursor.fetchall()
                entities_inserted = len(req.entities)
            except Exception as exc:
                logger.error("Batch entity insert failed: %s", exc)

        # Batch insert prim snapshots
        if req.prim_snapshots:
            values_rows = []
            for p in req.prim_snapshots:
                row = (
                    f"('{_esc(p.entity_path)}', '{_esc(p.relative_path)}', '{_esc(p.prim_type)}', "
                    f"'{_esc(p.properties)}', '{_esc(p.prim_hash)}', "
                    f"TIMESTAMP '{_esc(backup_ts)}')"
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

    return EntityBackupResponse(
        status="ok",
        entities_inserted=entities_inserted,
        prims_inserted=prims_inserted,
        backup_time=backup_ts,
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
    backup_time = _validate_timestamp(backup_time)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"is_dynamic, dynamic_table, child_count, entity_hash, usd_file_path, depends_on, backup_time "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE backup_time = TIMESTAMP '{_esc(backup_time)}' "
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
    time_a = _validate_timestamp(time_a)
    time_b = _validate_timestamp(time_b)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    def fetch_entities_at(ts: str) -> dict:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(
                f"SELECT entity_path, entity_hash, entity_type "
                f"FROM {catalog}.{ns}.entities "
                f"WHERE backup_time = TIMESTAMP '{_esc(ts)}'"
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
    time_a = _validate_timestamp(time_a)
    time_b = _validate_timestamp(time_b)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    def fetch_prims_at(ts: str) -> dict:
        with trino_cursor(schema=ns) as cursor:
            cursor.execute(
                f"SELECT relative_path, prim_type, prim_hash, properties "
                f"FROM {catalog}.{ns}.prim_snapshots "
                f"WHERE entity_path = '{_esc(entity_path)}' "
                f"AND backup_time = TIMESTAMP '{_esc(ts)}'"
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
    backup_time = _validate_timestamp(backup_time)
    ensure_entity_tables()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    # 1. Fetch all entities at this backup time
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"is_dynamic, dynamic_table, child_count, entity_hash, usd_file_path, depends_on "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE backup_time = TIMESTAMP '{_esc(backup_time)}'"
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
            f"WHERE backup_time = TIMESTAMP '{_esc(backup_time)}'"
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
    backup_time = _validate_timestamp(backup_time)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    paths = [p.strip() for p in relative_paths.split(",") if p.strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="relative_paths must not be empty")

    paths_list = ", ".join(f"'{_esc(p)}'" for p in paths)

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT relative_path, prim_type, properties, prim_hash "
            f"FROM {catalog}.{ns}.prim_snapshots "
            f"WHERE entity_path = '{_esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{_esc(backup_time)}' "
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
    backup_time = _validate_timestamp(backup_time)
    ensure_entity_tables()
    entity_path = "/" + entity_path if not entity_path.startswith("/") else entity_path
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    # Fetch entity record
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT entity_id, entity_path, entity_type, source_type, source_asset, "
            f"is_dynamic, dynamic_table, child_count, entity_hash, usd_file_path, depends_on "
            f"FROM {catalog}.{ns}.entities "
            f"WHERE entity_path = '{_esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{_esc(backup_time)}'"
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
            f"WHERE entity_path = '{_esc(entity_path)}' "
            f"AND backup_time = TIMESTAMP '{_esc(backup_time)}' "
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
#  POST /dynamic/sample-ingest
# ═══════════════════════════════════════════════════════════════════════

@router.post("/dynamic/sample-ingest", response_model=SampleIoTResponse)
async def sample_iot_ingest(req: SampleIoTRequest):
    """Generate and ingest fake IoT data for a dynamic entity."""
    from app.core.trino_config import init_dynamic_table

    # Derive a safe table name from entity path (strict validation)
    safe_id = _validate_table_id(req.entity_path.strip("/").replace("/", "_"))
    table_fqn = init_dynamic_table(safe_id)

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    table_name = f"dynamic_{safe_id}"

    inserted = 0
    with trino_cursor(schema=ns) as cursor:
        for _ in range(req.count):
            now = datetime.now(timezone.utc)
            ts = now.strftime("%Y-%m-%d %H:%M:%S.%f")
            px = round(random.uniform(-5.0, 5.0), 3)
            py = round(random.uniform(0.0, 2.0), 3)
            pz = round(random.uniform(-5.0, 5.0), 3)
            rx = round(random.uniform(-180, 180), 1)
            ry = round(random.uniform(-180, 180), 1)
            rz = round(random.uniform(-180, 180), 1)
            speed = round(random.uniform(0.0, 3.0), 2)
            oid = safe_id

            sql = (
                f"INSERT INTO {catalog}.{ns}.{table_name} "
                f"(object_id, timestamp, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z, speed, space_id, properties) "
                f"VALUES ('{oid}', TIMESTAMP '{ts}', {px}, {py}, {pz}, "
                f"{rx}, {ry}, {rz}, {speed}, 'sample', "
                f"'{{\"source\": \"sample-iot\", \"entity_path\": \"{_esc(req.entity_path)}\"}}')"
            )
            try:
                cursor.execute(sql)
                cursor.fetchall()
                inserted += 1
            except Exception as exc:
                logger.error("Sample IoT insert failed: %s", exc)

    return SampleIoTResponse(
        status="ok",
        entity_path=req.entity_path,
        records_generated=inserted,
        table_name=table_name,
    )


# ═══════════════════════════════════════════════════════════════════════
#  Utility
# ═══════════════════════════════════════════════════════════════════════

def _esc(val: str) -> str:
    """Escape single quotes for Trino SQL string literals."""
    if val is None:
        return ""
    return str(val).replace("'", "''")


def _validate_timestamp(ts: str) -> str:
    """Validate and normalize a timestamp string to prevent SQL injection."""
    try:
        dt = datetime.fromisoformat(ts.replace(" ", "T").rstrip("Z"))
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid timestamp format")


def _validate_table_id(val: str) -> str:
    """Validate a string is safe for use as a SQL table identifier."""
    safe = val.replace("-", "_").replace(" ", "_").lower()
    if not re.match(r"^[a-z0-9_]{1,128}$", safe):
        raise HTTPException(status_code=400, detail="Invalid identifier for table name")
    return safe
