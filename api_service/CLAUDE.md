# API Service — CLAUDE.md

## Module Overview

FastAPI middleware. Connects Nucleus Pipeline and Isaac Sim Extension to the Iceberg Lakehouse.

## Core Architecture

```
routers/entities.py  — Entity backup/restore/diff + Simulation sessions/deltas/keyframes/flush
routers/raw_backup.py — Raw file backup endpoints (Task 1)
api/v1/query.py      — Ad-hoc Trino SQL (read-only restricted)
api/v1/upload.py     — MinIO file upload/download
core/sql_utils.py    — SQL escape common utilities (esc, validate_timestamp, validate_table_id)
core/config.py       — Pydantic Settings (environment variable mapping)
schemas/entities.py  — Pydantic request/response models
services/            — Trino/S3/Iceberg service layer
```

## Key Rules

- `/api/v1/query` allows **read-only queries only** — blocks FORBIDDEN_KEYWORDS (DROP, DELETE, INSERT, etc.)
- `esc()`, `validate_timestamp()`, `validate_table_id()` must be imported from `core/sql_utils.py` (DRY)
- Do not duplicate these functions in `entities.py` or `raw_backup.py`
- Pydantic models with `Field(alias=...)` must use `model_dump(by_alias=True)`
- `EntityBackupResponse` has an `error: Optional[str]` field — delivers error messages on INSERT failure

## Schema Migration

- `ensure_entity_tables()` handles table creation + column validation
- If columns are missing from existing tables, **automatically DROPs and recreates** (lab environment only)
- Compares `_ENTITIES_EXPECTED_COLS` list against actual columns
- Uses recreation approach since Trino Iceberg has limited `ALTER TABLE ADD COLUMN` support

## Testing

```bash
cd api_service
.venv-test/Scripts/python.exe -m pytest tests/test_health.py tests/test_upload_usd.py \
  tests/test_catalog_init.py tests/test_static_iceberg.py \
  tests/test_static_prim_schemas.py tests/test_trino_client.py -v
```

- `test_dynamic_*`, `test_static_query_service.py`, etc. reference deleted modules → legacy (excluded from execution)
- Entity/Raw Backup router tests are not yet written (need to be added)

## Active Iceberg Tables (6)

| Table | Task | Bootstrap |
|-------|------|-----------|
| `entities` | Task 2 | `ensure_entity_tables()` |
| `prim_snapshots` | Task 2 | `ensure_entity_tables()` |
| `raw_backup_files` | Task 1 | `raw_backup.py` inline |
| `simulation_sessions` | Task 3 | `ensure_simulation_tables()` |
| `simulation_deltas` | Task 3 | `ensure_simulation_tables()` |
| `simulation_keyframes` | Task 3 | `ensure_simulation_tables()` |

## Active API Endpoints

### Entity (routers/entities.py)
- `POST /entities/backup` — Entity + Prim bulk insert
- `GET /entities/backup-times` — 백업 시간 목록
- `GET /entities/list` — 특정 시간 Entity 목록
- `GET /entities/diff` — Entity-level 비교
- `GET /entities/{path}/prim-diff` — Prim-level 비교
- `GET /entities/restore-all` — 전체 복원 데이터 (NDJSON)
- `GET /entities/{path}/restore-prims` — Entity Prim 스트리밍
- `GET /entities/{path}/restore` — Entity 복원 데이터
- `POST /realtime/flush` — Delta batch flush (sim 필드 감지 시 simulation_deltas 라우팅)

### Simulation (routers/entities.py)
- `POST /simulation/sessions` — 세션 생성
- `PATCH /simulation/sessions/{id}` — 세션 업데이트
- `GET /simulation/sessions` — 세션 목록
- `GET /simulation/deltas` — Delta bulk query (NDJSON 스트리밍)
- `POST /simulation/keyframes` — 키프레임 저장

### Raw Backup (routers/raw_backup.py)
- `POST /raw-backup/files` — 파일 레코드 bulk insert
- `GET /raw-backup/latest-files` — 최신 백업 파일 목록
- `GET /raw-backup/list` — 특정 시간 파일 목록
- `GET /raw-backup/times` — 백업 시간 목록
- `GET /raw-backup/diff` — 파일 비교

### Utility (api/v1/)
- `GET /health` — lightweight health check
- `POST /query` — Ad-hoc Trino SQL (read-only)
- `POST /upload-usd` — USD 파일 업로드 (MinIO)
- `GET /download-usd` — USD 파일 다운로드

## ToDo

- [ ] Parameterized query migration — `esc()` + f-string → `cursor.execute(sql, params)` (SQL injection 방지)
- [ ] Iceberg compaction schedule — `ALTER TABLE ... EXECUTE optimize` for simulation_deltas
