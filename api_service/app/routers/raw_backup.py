"""
Nucleus Raw Backup Router.

Endpoints:
    POST /api/v1/raw-backup/files         — Bulk insert raw backup file records
    GET  /api/v1/raw-backup/latest-files   — Get files from the latest backup
    GET  /api/v1/raw-backup/list           — List files at a specific backup time
    GET  /api/v1/raw-backup/times          — List available backup timestamps
    GET  /api/v1/raw-backup/diff           — Compare files between two backup times
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import trino_cursor, init_namespace

from app.schemas.raw_backup import (
    RawBackupDiffResponse,
    RawBackupFilesRequest,
    RawBackupFilesResponse,
    RawBackupTimesResponse,
)

router = APIRouter(tags=["Raw Backup"])

# Module-level flag to avoid repeated DDL on every request
_tables_ensured = False

# ═══════════════════════════════════════════════════════════════════════
#  Table Bootstrap
# ═══════════════════════════════════════════════════════════════════════

RAW_BACKUP_FILES_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.raw_backup_files (
    backup_time TIMESTAMP(6),
    folder_path VARCHAR,
    file_path VARCHAR,
    file_name VARCHAR,
    file_extension VARCHAR,
    file_size BIGINT,
    modified_time VARCHAR,
    s3_key VARCHAR,
    status VARCHAR,
    backup_source VARCHAR
) WITH (
    partitioning = ARRAY['day(backup_time)']
)
"""


def ensure_raw_backup_table() -> dict:
    """Create raw_backup_files table if it doesn't exist.

    Uses a module-level flag to skip redundant DDL after first success.
    """
    global _tables_ensured
    if _tables_ensured:
        return {"raw_backup_files": "ok (cached)"}

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    init_namespace(ns)

    results = {}
    with trino_cursor(schema=ns) as cursor:
        try:
            cursor.execute(RAW_BACKUP_FILES_DDL.format(catalog=catalog, namespace=ns))
            cursor.fetchall()
            results["raw_backup_files"] = "ok"
            logger.info("Ensured table: %s.%s.raw_backup_files", catalog, ns)
        except Exception as exc:
            results["raw_backup_files"] = f"error: {exc}"
            logger.warning("Table creation issue for raw_backup_files: %s", exc)

    if all(v == "ok" for v in results.values()):
        _tables_ensured = True

    return results


# ═══════════════════════════════════════════════════════════════════════
#  POST /raw-backup/files
# ═══════════════════════════════════════════════════════════════════════

@router.post("/raw-backup/files", response_model=RawBackupFilesResponse)
async def backup_files(req: RawBackupFilesRequest):
    """Bulk insert raw backup file records into Iceberg."""
    ensure_raw_backup_table()

    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    backup_ts = _validate_timestamp(req.backup_time)

    files_inserted = 0
    batch_size = 500

    with trino_cursor(schema=ns) as cursor:
        # Batch in groups of 500 to avoid oversized SQL
        for i in range(0, len(req.files), batch_size):
            batch = req.files[i : i + batch_size]
            values_rows = []
            for f in batch:
                s3_val = "NULL" if f.s3_key is None else f"'{_esc(f.s3_key)}'"
                row = (
                    f"(TIMESTAMP '{_esc(backup_ts)}', '{_esc(req.folder_path)}', "
                    f"'{_esc(f.file_path)}', '{_esc(f.file_name)}', "
                    f"'{_esc(f.file_extension)}', {f.file_size}, '{_esc(f.modified_time)}', "
                    f"{s3_val}, '{_esc(f.status)}', '{_esc(req.backup_source)}')"
                )
                values_rows.append(row)

            sql = (
                f"INSERT INTO {catalog}.{ns}.raw_backup_files "
                f"(backup_time, folder_path, file_path, file_name, file_extension, file_size, "
                f"modified_time, s3_key, status, backup_source) "
                f"VALUES {', '.join(values_rows)}"
            )
            try:
                cursor.execute(sql)
                cursor.fetchall()
                files_inserted += len(batch)
            except Exception as exc:
                logger.error("Batch raw backup insert failed: %s", exc)

    status = "ok" if files_inserted == len(req.files) else ("partial" if files_inserted > 0 else "error")
    return RawBackupFilesResponse(
        status=status,
        files_inserted=files_inserted,
        backup_time=backup_ts,
    )


# ═══════════════════════════════════════════════════════════════════════
#  GET /raw-backup/latest-files
# ═══════════════════════════════════════════════════════════════════════

@router.get("/raw-backup/latest-files")
async def latest_files(
    folder_path: str = Query(None, description="Nucleus folder path to filter by"),
):
    """Return files from the most recent backup snapshot, optionally filtered by folder."""
    ensure_raw_backup_table()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    folder_filter = ""
    if folder_path:
        folder_filter = f" AND folder_path = '{_esc(folder_path)}'"

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT backup_time, file_path, file_name, file_extension, "
            f"file_size, modified_time, s3_key, status "
            f"FROM {catalog}.{ns}.raw_backup_files "
            f"WHERE backup_time = ("
            f"SELECT MAX(backup_time) FROM {catalog}.{ns}.raw_backup_files"
            f" WHERE 1=1{folder_filter}"
            f"){folder_filter}"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    if not rows:
        return {"backup_time": None, "files": []}

    files = []
    bt = None
    for row in rows:
        rec = {}
        for i, col in enumerate(cols):
            val = row[i]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            rec[col] = val
        if bt is None:
            bt = rec.get("backup_time")
        files.append(rec)

    return {"backup_time": bt, "files": files}


# ═══════════════════════════════════════════════════════════════════════
#  GET /raw-backup/list
# ═══════════════════════════════════════════════════════════════════════

@router.get("/raw-backup/list")
async def list_files(backup_time: str = Query(..., description="Backup timestamp")):
    """List all files at a specific backup time (excluding deleted)."""
    backup_time = _validate_timestamp(backup_time)
    ensure_raw_backup_table()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT backup_time, file_path, file_name, file_extension, "
            f"file_size, modified_time, s3_key, status "
            f"FROM {catalog}.{ns}.raw_backup_files "
            f"WHERE backup_time = TIMESTAMP '{_esc(backup_time)}' "
            f"AND status != 'deleted' "
            f"ORDER BY file_path"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    files = []
    for row in rows:
        rec = {}
        for i, col in enumerate(cols):
            val = row[i]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            rec[col] = val
        files.append(rec)

    return {"backup_time": backup_time, "files": files}


# ═══════════════════════════════════════════════════════════════════════
#  GET /raw-backup/times
# ═══════════════════════════════════════════════════════════════════════

@router.get("/raw-backup/times")
async def get_backup_times():
    """Return distinct backup timestamps with folder paths."""
    ensure_raw_backup_table()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT DISTINCT CAST(backup_time AS VARCHAR) AS bt, "
            f"COALESCE(folder_path, '') AS folder_path "
            f"FROM {catalog}.{ns}.raw_backup_files "
            f"ORDER BY bt DESC"
        )
        rows = cursor.fetchall()

    snapshots = [{"backup_time": row[0], "folder_path": row[1]} for row in rows]
    return {"backup_times": [r[0] for r in rows], "snapshots": snapshots}


# ═══════════════════════════════════════════════════════════════════════
#  GET /raw-backup/diff
# ═══════════════════════════════════════════════════════════════════════

@router.get("/raw-backup/diff", response_model=RawBackupDiffResponse)
async def diff_backup(
    time_a: str = Query(..., description="First backup timestamp"),
    time_b: str = Query(..., description="Second backup timestamp"),
):
    """Return files at time_b with status new/modified/deleted."""
    time_a = _validate_timestamp(time_a)
    time_b = _validate_timestamp(time_b)
    ensure_raw_backup_table()
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace

    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SELECT file_path, file_name, file_extension, file_size, "
            f"modified_time, s3_key, status "
            f"FROM {catalog}.{ns}.raw_backup_files "
            f"WHERE backup_time = TIMESTAMP '{_esc(time_b)}' "
            f"AND status IN ('new', 'modified', 'deleted')"
        )
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    files = []
    new_count = modified_count = deleted_count = unchanged_count = 0
    for row in rows:
        rec = {}
        for i, col in enumerate(cols):
            val = row[i]
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            rec[col] = val
        files.append(rec)

        st = rec.get("status")
        if st == "new":
            new_count += 1
        elif st == "modified":
            modified_count += 1
        elif st == "deleted":
            deleted_count += 1
        else:
            unchanged_count += 1

    return RawBackupDiffResponse(
        time_a=time_a,
        time_b=time_b,
        new=new_count,
        modified=modified_count,
        deleted=deleted_count,
        unchanged=unchanged_count,
        files=files,
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
