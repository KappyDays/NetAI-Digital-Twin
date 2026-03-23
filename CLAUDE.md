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

### 2. API Service (FastAPI Middleware)

Located at `api_service/`. Bridges Isaac Sim extensions to the Iceberg Lakehouse.

**Key endpoints:**
- `GET /health` — Deep health check with dependency status
- `GET /api/v1/health` — Lightweight health check
- `POST /api/v1/prims` — Insert static Prim records (Iceberg)
- `POST /api/v1/dynamic/ingest` — Ingest dynamic object IoT data (per-object Iceberg tables)
- `POST /api/v1/upload-usd` — Upload USD files (MinIO/S3)
- `POST /api/v1/query` — Ad-hoc Trino SQL query
- `GET /api/v1/spaces/congestion/summary` — Space congestion aggregation
- `GET /api/v1/dynamic/query/latest` — Latest dynamic object states

### 3. Omniverse Extension (Isaac Sim)

`Omniverse/omniverse-extensions/lakehouse.proto/` — the only extension in this branch.

**Extension structure:** `config/extension.toml` (metadata), `extension.py` (boilerplate), `ui_builder.py` (UI + logic), `global_variables.py` (constants).

**Two tasks:**
- Task 1: Scans all Stage Prims and inserts to Iceberg via `POST /api/v1/prims`
- Task 2: Exports /World child Prims as USD files and uploads via `POST /api/v1/upload-usd`

API URL configurable via `LAKEHOUSE_API_URL` env var (default: `http://lakehouse-api:8000`).
Omniverse extensions use `urllib` only (no external pip packages inside Isaac Sim).

### 4. Web Dashboard

`dashboard/` — React SPA (Vite) with congestion heatmap, time-series charts, and Trino SQL interface. Served via nginx reverse proxy on port 3000.

## Data Flow

```
Isaac Sim (lakehouse.proto) -> Lakehouse API (FastAPI:8100) -> Polaris/Iceberg (metadata)
                                                             -> MinIO/S3 (USD files)

Trino (SQL:8900) -> Polaris REST Catalog -> MinIO/S3 (Iceberg tables)

Web Dashboard (:3000) -> nginx -> Lakehouse API (:8100) -> Trino -> Iceberg
```

## Testing

```bash
cd api_service && python -m pytest tests/ -v    # 576 tests, ~45s
```

## Key Conventions

- `docker compose` must run from `Lakehouse/Iceberg/`, NOT project root
- Environment configs use `.env` files (never committed; see `example.env`)
- All container healthchecks use `127.0.0.1` instead of `localhost` (Tailscale DNS interference)
- MinIO requires `MINIO_DOMAIN=minio` + Docker network aliases for virtual-hosted-style S3 access
- Polaris needs `CATALOG_MANAGE_CONTENT` grant after each container recreation
- Pydantic models with `Field(alias=...)` must use `model_dump(by_alias=True)` when passing to Iceberg
- The `nuscenes_experiment/` directory contains performance benchmarking (Python loops vs. Spark Iceberg)
- Active branch: `lab/exts-lakehouse` (UWB, TwinX, Datacenter, DeltaLake removed)

## Deployment Gotchas

- Windows to Linux: use `git clone -b <branch>` (not rsync) to auto-apply `.gitattributes` LF normalization
- Docker image tags from AI code generation may reference future dates — verify tags exist or use `:latest`
- `docker-compose.yml` healthcheck overrides Dockerfile HEALTHCHECK — check both when debugging
- Polaris `CATALOG_MANAGE_CONTENT` grant resets on container recreation — `init-polaris-catalog.sh` should re-grant
- See `Lakehouse/Iceberg/DEPLOYMENT_GUIDE.md` for full server deployment guide

<!-- ooo:START -->
<!-- ooo:VERSION:0.24.0 -->
# Ouroboros — Specification-First AI Development

> Before telling AI what to build, define what should be built.
> As Socrates asked 2,500 years ago — "What do you truly know?"
> Ouroboros turns that question into an evolutionary AI workflow engine.

Most AI coding fails at the input, not the output. Ouroboros fixes this by
**exposing hidden assumptions before any code is written**.

1. **Socratic Clarity** — Question until ambiguity ≤ 0.2
2. **Ontological Precision** — Solve the root problem, not symptoms
3. **Evolutionary Loops** — Each evaluation cycle feeds back into better specs

```
Interview → Seed → Execute → Evaluate
    ↑                           ↓
    └─── Evolutionary Loop ─────┘
```

## ooo Commands

Each command loads its agent/MCP on-demand. Details in each skill file.

| Command | Loads |
|---------|-------|
| `ooo` | — |
| `ooo interview` | `ouroboros:socratic-interviewer` |
| `ooo seed` | `ouroboros:seed-architect` |
| `ooo run` | MCP required |
| `ooo evolve` | MCP: `evolve_step` |
| `ooo evaluate` | `ouroboros:evaluator` |
| `ooo unstuck` | `ouroboros:{persona}` |
| `ooo status` | MCP: `session_status` |
| `ooo setup` | — |
| `ooo help` | — |

## Agents

Loaded on-demand — not preloaded.

**Core**: socratic-interviewer, ontologist, seed-architect, evaluator,
wonder, reflect, advocate, contrarian, judge
**Support**: hacker, simplifier, researcher, architect
<!-- ooo:END -->
