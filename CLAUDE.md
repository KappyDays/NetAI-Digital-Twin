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

Located at `api_service/`. Bridges Isaac Sim extensions and Nucleus Pipeline to the Iceberg Lakehouse.

**Key endpoints:**
- `GET /api/v1/health` — Lightweight health check
- `POST /api/v1/query` — Ad-hoc Trino SQL query
- `POST /api/v1/upload-usd` — Upload USD files (MinIO/S3)
- `POST /api/v1/entities/backup` — Entity + Prim snapshot backup
- `GET /api/v1/entities/backup-times` — List backup timestamps
- `GET /api/v1/entities/list?backup_time=T` — List entities at timestamp
- `GET /api/v1/entities/diff?time_a=T1&time_b=T2` — Entity-level diff
- `GET /api/v1/entities/{path}/prim-diff?time_a=T1&time_b=T2` — Prim-level diff
- `GET /api/v1/entities/{path}/restore?backup_time=T` — Single entity restore data
- `GET /api/v1/entities/restore-all?backup_time=T` — All entities restore data
- `POST /api/v1/raw-backup/files` — Raw backup file metadata insert
- `GET /api/v1/raw-backup/times` — Raw backup timestamps
- `GET /api/v1/raw-backup/diff?time_a=T1&time_b=T2` — Raw file diff

### 3. Nucleus Pipeline (CLI)

`nucleus_pipeline/` — Python CLI for Nucleus server backup operations.

**Two modes:**
- **Task 1 (Raw Backup):** `python main.py --raw-backup --nucleus-folder <URI>` — Incremental folder backup to MinIO with Iceberg metadata tracking
- **Task 2 (Entity Backup):** `python main.py --nucleus-path <URI>` — Extract root layer overrides from USD, store Entity/Prim snapshots in Iceberg

**Dependencies:** `pxr` (OpenUSD), `omni.client` (Nucleus). Runs as subprocess to avoid DLL conflicts.

### 4. Omniverse Extensions (Isaac Sim)

`Omniverse/omniverse-extensions/` — Isaac Sim 5.1.0 Extensions.

**KKR.Lakehouse** (`lakehouse.proto/`) — *Deprecated, not part of active Task 1/2/3 workflow:*
- Prim scan to Iceberg (experimental)
- USD export to MinIO (experimental)

**KKR.TimeTravel** (`time.travel/`) — *Task 3 (Time Travel Restore):*
- Stage/Entity restore from Iceberg backup timestamps
- 3 restore modes: Changes Only / Full Entity / Full All
- Undo (memory snapshot) + Nucleus Reopen
- API URL preset: Local (`localhost:8100`) / Docker (`lakehouse-api:8000`)

**Extension conventions:**
- Menu: Tools > KKR-Tools submenu
- stdlib only (`urllib`, no pip packages inside Isaac Sim)
- API URL configurable via `LAKEHOUSE_API_URL` env var

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
cd api_service && python -m pytest tests/ -v
```

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
