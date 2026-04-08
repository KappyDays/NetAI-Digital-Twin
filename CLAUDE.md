# CLAUDE.md

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

**Trino naming:** Catalog `polaris`, Namespace `netai` (e.g. `polaris.netai.<table>`). Tables are defined in code and SQL scripts.

### 2. API Service (FastAPI Middleware)

`api_service/` — FastAPI. Main routers: `app/routers/entities.py` (Entity backup/restore/diff + Simulation API), `app/routers/raw_backup.py` (Raw file backup), and `app/routers/dynamic_prims.py` (DynamicPrim IoT streaming). Additional: `app/api/v1/query.py` (ad-hoc SQL), `app/api/v1/upload.py` (USD upload/download).

**Iceberg Tables (7+ active):**

| Table | Task | Purpose |
|-------|------|---------|
| `raw_backup_files` | Task 1 | Nucleus folder file metadata |
| `entities` | Task 2 | Entity metadata + backup snapshots |
| `prim_snapshots` | Task 2 | Prim hierarchy snapshots |
| `simulation_sessions` | Task 3 | M&S capture session metadata |
| `simulation_deltas` | Task 3 | M&S property delta records |
| `simulation_keyframes` | Task 3 | M&S keyframe full state snapshots |
| `hum_temp_sensor1` (+ per-sensor) | Task 4 | DynamicPrim IoT streaming data (1 Prim = 1 Table) |

**Task 4 (DynamicPrim IoT):** 센서별 독립 Iceberg 테이블로 (준)실시간 IoT 스트리밍 데이터 저장. Isaac Sim Prim(`/World/Dynamic/*`)과 1:1 매핑. 라우터: `app/routers/dynamic_prims.py`. entities 테이블과 독립 운영.

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

**KKR.TimeTravel** (`time.travel/`) — *Task 3 (Time Travel Restore) + M&S Capture & Replay*

**Extension conventions:**
- stdlib only (`urllib`, no pip packages inside Isaac Sim)
- PhysX 콜백 내 JSON/네트워크/Stage traversal 금지 — cached attr.Get()만 허용

### 5. Web Dashboard

`dashboard/` — React SPA (Vite) with Entity Diff viewer, Raw Backup explorer, Pipeline Monitor (Task 1~4 Iceberg tables live view), and Trino SQL interface. Served via nginx reverse proxy on port 3000.

## Testing

```bash
cd api_service && python -m pytest tests/ -v
```

> Note: `test_static_iceberg.py::TestStaticTableInfo::test_returns_schema_fields` is a known pre-existing failure (`settings.iceberg_table_name` missing). All other 200 tests pass. Legacy test files (test_dynamic_*, test_spaces, test_prims, etc.) have been removed.

## Entity Model

- **Entity boundary**: Reference/Payload composition arc or Container Xform directly under `/World`
- **Override-only**: Extracts only root layer overrides (excludes sublayer/session layer)
- **entity_id**: `uuid5(NAMESPACE_URL, entity_path)` — deterministic, same ID across backups
- **entity_hash**: SHA-256(sorted sub-prim hashes)[:16] — Tier 1 fields only (audit excluded)
- **depends_on**: Extracts cross-Entity dependencies from relationship target paths
- **Nested Entity**: Stops collecting overrides at child Entity boundaries (prevents duplication)
- **float normalization**: `round(v, 9)` applied (prevents false positive hash)
- **Restore verification**: After restore, recalculates hash from Stage and compares with backup hash

### Property Extraction: Field-Driven + 2-Tier Architecture

Extraction uses `ListInfoKeys()` on both `Sdf.PrimSpec` and `Sdf.PropertySpec` levels (field-driven, not hand-picked).

**Data format**: JSON nested dict (not flat prefix dict):
```json
{
  "typeName": "Xform", "specifier": "over",
  "meta": {"kind": "...", "instanceable": true, ...},
  "props": {"xformOp:translate": {"value": [...], "type": "double3"}, "material:binding": {"targets": {...}, "type": "rel", "metadata": {"bindMaterialAs": "strongerThanDescendants"}}},
  "audit": {"prim": {"references": ...}, "props": {"attr": {"variability": "Varying"}}}
}
```

**Tier classification**:
- **Tier 1 (hash + restore)**: typeName, specifier, kind, instanceable, active, hidden, customData, assetInfo, apiSchemas, variantSelection, documentation, comment + property values/targets/connections/metadata (bindMaterialAs, colorSpace, displayGroup, etc.)
- **Tier 2 (audit only)**: references, payload, inherits, specializes, variantSetNames, primOrder, propertyOrder, variability
- **Legacy compat**: `_is_nested_format()` detects old flat dict → `_apply_properties_legacy()` fallback

## Key Conventions

- `docker compose` must run from `Lakehouse/Iceberg/`, NOT project root
- All container healthchecks use `127.0.0.1` instead of `localhost` (Tailscale DNS interference)
- MinIO requires `MINIO_DOMAIN=minio` + Docker network aliases for virtual-hosted-style S3 access
- Polaris needs `CATALOG_MANAGE_CONTENT` grant after each container recreation — `init-polaris-catalog.sh` re-grants
- Pydantic models with `Field(alias=...)` must use `model_dump(by_alias=True)` when passing to Iceberg
- `_extract_layer_overrides()` in `usd_parser.py` and `restore_engine.py` must stay in sync — field-driven `ListInfoKeys()` approach producing identical nested dict output. Shared functions: `_serialize_field()`, `_serialize_list_op()`, `_to_json_value()`, `_compute_prim_hash()`, Tier constants (TIER1/2_PRIM_KEYS, TIER1/2_PROP_KEYS)
- **Iceberg 테이블 변경 시 Dashboard 동기화 필수**: 테이블 추가/삭제/스키마 변경 시 아래 3곳을 반드시 함께 업데이트
  - `dashboard/src/components/QueryPanel.jsx` — `PRESET_GROUPS`의 Discovery(DESCRIBE), Data Preview(SELECT), Clear Data(DELETE) 프리셋
  - `dashboard/src/pages/PipelineMonitorPage.jsx` — `TABLES` 객체의 Task별 테이블 목록 (sql, deleteSql)
  - `dashboard/src/utils/icebergSql.js` — 필요 시 SQL 템플릿 함수 추가

## Agent Delegation Guide

### Available Agents

| Agent | Scope | Model | When to Use |
|-------|-------|-------|-------------|
| `lakehouse-backend` | api_service/ + Lakehouse/Iceberg/ | Sonnet (↑Opus) | API endpoints, schemas, Trino SQL, Docker infra, stack ops |
| `isaac-sim-expert` | time.travel/ + nucleus_pipeline/ | **Opus** | USD parsing, M&S capture/replay, Stage restore, Entity detection |
| `frontend` | dashboard/ | Sonnet (↑Opus) | React pages, API contract consumption, Iceberg visualization |

### Critical Cross-Module Rules

1. **Extraction sync**: `usd_parser.py` and `restore_engine.py` share 6 identical functions (`_extract_layer_overrides`, `_serialize_field`, `_serialize_list_op`, `_to_json_value`, `_compute_prim_hash`, Tier constants) — `isaac-sim-expert` owns both sides
2. **API contract**: `entities.py` response change → update `dashboard/src/api.js` (`frontend`) + Extension `api_client.py` (`isaac-sim-expert`)
3. **Simulation flush contract**: `capture_coordinator.py` flush format change → sync `entities.py` routing logic
4. **Runner WebSocket contract**: `runner_server.py` protocol change → sync `PipelineGuidePage.jsx`
5. **Inactive Extensions (do not modify)**: `physics.simulation`, `dynamic.tracker`, `space.heatmap`, `object.detector`, `stagegraph.viewer`, `lakehouse.proto` — legacy
6. **Iceberg 테이블 변경**: `entities.py` DDL 변경 → `QueryPanel.jsx` 프리셋 + `PipelineMonitorPage.jsx` 테이블 목록 동기화 (`lakehouse-backend` + `frontend`)
7. **DynamicPrim API contract**: `dynamic_prims.py` 변경 → `QueryPanel.jsx` Task 4 프리셋 + `PipelineMonitorPage.jsx` Task 4 테이블 목록 동기화

