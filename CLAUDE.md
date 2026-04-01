# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NetAI-Digital-Twin is a network AI digital twin platform built on an **Iceberg Lakehouse** data infrastructure with **NVIDIA Omniverse/Isaac Sim** integration. The active branch (`lab/exts-lakehouse`) focuses on the Lakehouse stack only.

## Architecture

### 1. Iceberg Lakehouse (Data Infrastructure)

Apache Polaris (REST catalog) + MinIO (S3) + Trino (SQL engine) + Lakehouse API middleware (FastAPI) + React Dashboard (nginx). The `lakehouse-api` build context is at `../../api_service` relative to the docker-compose.

**Stack startup:**
```bash
cd Lakehouse/Iceberg
cp example.env .env        # configure credentials (MinIO user >= 5 chars, password >= 8 chars)
chmod +x scripts/*.sh start.sh
./start.sh                 # runs docker compose up -d --build
```

**Ports:**

| Service | Port | Purpose |
|---|---|---|
| MinIO API | 9000 | S3-compatible storage |
| MinIO Console | 9001 | Web management UI |
| Polaris REST | 8181 | Iceberg REST Catalog |
| Polaris Health | 8182 | Management endpoint |
| Trino | 8900 | SQL query engine (mapped from 8080) |
| Lakehouse API | 8100 | FastAPI middleware (mapped from 8000) |
| Dashboard | 3000 | React web dashboard (nginx) |

**Trino naming:**
- Catalog: `polaris` (Trino properties file: `trino/catalog/polaris.properties`)
- Namespace: `netai`
- Tables: `polaris.netai.entities`, `polaris.netai.prim_snapshots`, `polaris.netai.raw_backup_files`

### 2. API Service (FastAPI Middleware)

`api_service/` — FastAPI. Endpoints are in `app/routers/entities.py` and `app/routers/raw_backup.py`.

### 3. Nucleus Pipeline (CLI)

`nucleus_pipeline/` — Python CLI for Nucleus server backup operations.

**Two modes:**
- **Task 1 (Raw Backup):** `python main.py --raw-backup --nucleus-folder <URI>` — Incremental folder backup to MinIO with Iceberg metadata tracking
- **Task 2 (Entity Backup):** `python main.py --nucleus-path <URI>` — Extract root layer overrides from USD, store Entity/Prim snapshots in Iceberg

**Combined mode:**
- **Full Backup:** `python main.py --full-backup --nucleus-folder <URI> --nucleus-path <USD>` — Task 1 + Task 2 with shared backup_time

**Dependencies:** `pxr` (OpenUSD), `omni.client` (Nucleus). Runs as subprocess to avoid DLL conflicts.

### 4. Omniverse Extensions (Isaac Sim)

`Omniverse/omniverse-extensions/` — Isaac Sim 5.1.0 Extensions.

**KKR.TimeTravel** (`time.travel/`) — *Task 3 (Time Travel Restore)*

**Extension conventions:**
- Menu: Tools > KKR-Tools submenu
- stdlib only (`urllib`, no pip packages inside Isaac Sim)
- USD Stage API는 반드시 main thread에서 호출 — `run_in_executor` 사용 금지 (무증상 데드락)

### 5. Web Dashboard

`dashboard/` — React SPA (Vite) with Entity Diff viewer, Raw Backup explorer, and Trino SQL interface. Served via nginx reverse proxy on port 3000.

## Data Flow

```
Nucleus Pipeline (Task 1) -> Lakehouse API (:8100) -> MinIO/S3 (raw files)
                                                    -> Iceberg (raw_backup_files)

Nucleus Pipeline (Task 2) -> Lakehouse API (:8100) -> Iceberg (entities + prim_snapshots)
                                                    -> MinIO/S3 (USD files)

Isaac Sim (KKR.TimeTravel) -> Lakehouse API (:8100) -> Iceberg (read backup data)
                                                     -> Stage (apply overrides)

Trino (SQL:8900) -> Polaris REST Catalog -> MinIO/S3 (Iceberg tables)

Web Dashboard (:3000) -> nginx -> Lakehouse API (:8100) -> Trino -> Iceberg
```

## Testing

```bash
cd api_service && python -m pytest tests/ -v \
  --ignore=tests/test_dynamic_object_service.py \
  --ignore=tests/test_dynamic_objects.py \
  --ignore=tests/test_dynamic_query_service.py
```

> Note: `test_dynamic_*` and `test_static_query_service.py` 등 레거시 테스트는 삭제된 모듈을 참조하여 실패함 (미사용 Dynamic/Static 서비스). Entity 관련 테스트는 정상 통과.

## Entity Model

- **Entity boundary**: Reference/Payload composition arc 또는 `/World` 직속 Container Xform
- **Override-only**: root layer override만 추출 (sublayer/session layer 미포함)
- **entity_id**: `uuid5(NAMESPACE_URL, entity_path)` — deterministic, 백업 간 동일 ID
- **entity_hash**: SHA-256(sorted sub-prim hashes)[:16] — 변경 감지용
- **depends_on**: relationship target path에서 교차 Entity 의존성 추출
- **중첩 Entity**: 자식 Entity 경계에서 override 수집 중단 (중복 방지)
- **float 정규화**: `round(v, 9)` 적용 (false positive hash 방지)
- **복원 검증**: restore 후 Stage에서 hash 재계산하여 backup hash와 비교
- **Entity 감지 전략**: `Sdf.Layer` 순회가 primary (Reference/Payload 모두 감지). `Usd.Stage.Open(LoadNone)`은 Payload prim을 `GetChildren()`에서 숨기므로 primary로 사용 금지. Stage 순회는 sublayer prim 보충용으로만 사용.
- **ListOp 완전 검사**: `referenceList`/`payloadList`의 `prependedItems` + `appendedItems` + `explicitItems` 모두 확인 필수 (Isaac Sim drag-and-drop은 `explicitItems` 사용)

## Key Conventions

- `docker compose` must run from `Lakehouse/Iceberg/`, NOT project root
- Environment configs use `.env` files (never committed; see `example.env`)
- All container healthchecks use `127.0.0.1` instead of `localhost` (Tailscale DNS interference)
- MinIO requires `MINIO_DOMAIN=minio` + Docker network aliases for virtual-hosted-style S3 access
- Polaris needs `CATALOG_MANAGE_CONTENT` grant after each container recreation
- Pydantic models with `Field(alias=...)` must use `model_dump(by_alias=True)` when passing to Iceberg
- Active branch: `lab/exts-lakehouse` (UWB, TwinX, Datacenter, DeltaLake removed)

## Deployment Gotchas

- Windows to Linux: use `git clone -b <branch>` (not rsync) to auto-apply `.gitattributes` LF normalization
- Docker image tags from AI code generation may reference future dates — verify tags exist or use `:latest`
- `docker-compose.yml` healthcheck overrides Dockerfile HEALTHCHECK — check both when debugging
- Polaris `CATALOG_MANAGE_CONTENT` grant resets on container recreation — `init-polaris-catalog.sh` should re-grant
- See `Lakehouse/Iceberg/DEPLOYMENT_GUIDE.md` for full server deployment guide
- See `docs/E2E_SCENARIO_GUIDE.md` for Task 1/2/3 end-to-end scenario guide with Iceberg query examples
