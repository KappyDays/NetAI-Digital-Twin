# NetAI-Digital-Twin

Network AI Digital Twin 플랫폼 — **Iceberg Lakehouse** 데이터 인프라 위에 **NVIDIA Omniverse/Isaac Sim** 기반 Digital Twin을 구축하고, **Nucleus Pipeline**으로 Stage 백업/복원/타임트래블을 제공합니다.

## Architecture

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  Nucleus Pipeline (Task 1│    │  Nucleus Pipeline (Task 2)│
│  Raw Backup CLI)         │    │  Entity Backup CLI)       │
└───────────┬──────────────┘    └───────────┬──────────────┘
            │ POST /api/v1/raw-backup/files  │ POST /api/v1/entities/backup
            │                               │ POST /api/v1/upload-usd
            ▼                               ▼
┌───────────────────────────────────────────────────────────┐
│                   Lakehouse API (FastAPI) :8100            │
└──────────┬───────────────┬──────────────────┬─────────────┘
           │               │                  │
    ┌──────▼──┐       ┌────▼───┐     ┌────────▼──────┐
    │  Trino  │       │ MinIO  │     │    Polaris     │
    │  :8900  │       │ :9000  │     │    :8181       │
    │  (SQL)  │       │  (S3)  │     │ (REST Catalog) │
    └─────────┘       └────────┘     └───────────────┘
           │               │                  │
           └───────────────┴──────────────────┘
                       Iceberg Tables
                     (Parquet on MinIO)
           ▲                               ▲
           │ GET /api/v1/entities/*        │ fetch API
┌──────────┴───────────────┐    ┌──────────┴───────────┐
│  KKR.TimeTravel (Task 3) │    │  Web Dashboard :3000  │
│  Isaac Sim Extension     │    │  (React + nginx)      │
└──────────────────────────┘    └──────────────────────┘
```

## Quick Start

### 1. Prerequisites

- Docker Desktop (with Compose v2)
- Git

### 2. Clone & Setup

```bash
git clone -b lab/exts-lakehouse https://github.com/<org>/NetAI-Digital-Twin.git
cd NetAI-Digital-Twin/Lakehouse/Iceberg
cp example.env .env    # 필수: MinIO user >= 5자, password >= 8자
```

### 3. Start Stack

```bash
chmod +x scripts/*.sh start.sh
./start.sh
# 또는: docker compose up -d --build
```

### 4. Verify

```bash
./scripts/verify-stack.sh
# 또는 개별 확인:
curl http://localhost:8100/api/v1/health     # API
curl http://localhost:9001                    # MinIO Console
curl http://localhost:3000                    # Dashboard
```

## Services & Ports

| Service | Port | URL | Purpose |
|---------|------|-----|---------|
| MinIO API | 9000 | — | S3-compatible object storage |
| MinIO Console | 9001 | http://localhost:9001 | Web management UI |
| Polaris REST | 8181 | — | Iceberg REST Catalog |
| Polaris Health | 8182 | — | Management endpoint |
| Trino | 8900 | — | SQL query engine |
| Lakehouse API | 8100 | http://localhost:8100 | FastAPI middleware |
| Dashboard | 3000 | http://localhost:3000 | React web dashboard |

---

## Components

### 1. Lakehouse API (FastAPI)

`api_service/` — Isaac Sim Extension과 Nucleus Pipeline을 Iceberg Lakehouse에 연결하는 미들웨어.

#### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Deep health check (dependency status 포함) |
| `GET` | `/api/v1/health` | Lightweight health check |
| `POST` | `/api/v1/upload-usd` | USD 파일 MinIO 업로드 (s3_key 지정 가능) |
| `GET` | `/api/v1/download-usd?s3_key=...` | MinIO에서 USD 파일 다운로드 |
| `POST` | `/api/v1/query` | Ad-hoc Trino SQL 실행 |

#### Entity Backup/Restore/Diff (Task 2)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/entities/backup` | Entity + Prim Snapshot 일괄 저장 |
| `GET` | `/api/v1/entities/backup-times` | 백업 시점 목록 (backup_source 포함) |
| `GET` | `/api/v1/entities/list?backup_time=...` | 특정 시점의 Entity 목록 |
| `GET` | `/api/v1/entities/diff?time_a=...&time_b=...` | 두 시점 Entity 비교 |
| `GET` | `/api/v1/entities/{path}/prim-diff?time_a=...&time_b=...` | Entity 내부 Prim 비교 |
| `GET` | `/api/v1/entities/{path}/restore?backup_time=...` | Entity 복원 데이터 조회 |
| `GET` | `/api/v1/entities/restore-all?backup_time=...` | 전체 Entity 복원 데이터 조회 |

#### Raw Backup (Task 1)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/raw-backup/files` | Raw 백업 파일 메타데이터 삽입 |
| `GET` | `/api/v1/raw-backup/times` | Raw 백업 시점 목록 |
| `GET` | `/api/v1/raw-backup/diff?time_a=...&time_b=...` | 두 시점 Raw 파일 비교 |

#### Test

```bash
cd api_service
python -m pytest tests/ -v    # 576 tests, ~45s
```

---

### 2. Nucleus Pipeline (CLI)

`nucleus_pipeline/` — Isaac Sim 없이 Nucleus 서버(10.38.38.48)와 통신하여 폴더/파일을 백업하는 독립 CLI 도구. 두 가지 모드로 동작한다.

#### Install (Python 3.11 권장)

```bash
cd nucleus_pipeline
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt

# (Optional) Nucleus 서버 접속을 위한 omniverseclient
pip install omniverseclient --extra-index-url https://pypi.nvidia.com
```

#### Task 1: Raw Backup (폴더 통째 백업)

Nucleus 폴더 전체를 MinIO에 업로드하고, 파일 메타데이터를 Iceberg `raw_backup_files` 테이블에 기록. 증분(incremental) 방식으로 변경된 파일만 업로드.

```bash
# Nucleus 폴더 전체 Raw 백업
python main.py --raw-backup --nucleus-folder omniverse://10.38.38.48/Projects/ --api-url http://localhost:8100
```

#### Task 2: Entity Backup (USD Layer 기반 백업)

USD 파일의 Root Layer Override를 파싱하여 Entity + Prim 스냅샷을 Iceberg에 저장하고, USD 바이너리를 MinIO에 업로드.

```bash
# 로컬 USD 파일 백업
python main.py --local-path ../Omniverse/setup_stage.usda --api-url http://localhost:8100

# Nucleus 서버에서 다운로드 + 백업
python main.py --nucleus-path omniverse://10.38.38.48/Projects/scene.usd --api-url http://localhost:8100

# USD 파일 업로드 건너뛰기 (Override + Iceberg만)
python main.py --local-path ./scene.usda --api-url http://localhost:8100 --skip-usd-upload
```

#### CLI Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--raw-backup` | Task 1: Raw 폴더 백업 모드 활성화 | — |
| `--nucleus-folder` | Task 1: 백업할 Nucleus 폴더 URI | — |
| `--local-path` | Task 2: 로컬 USD/USDA 파일 경로 | — |
| `--nucleus-path` | Task 2: Nucleus 경로 (omniverse://...) | — |
| `--api-url` | Lakehouse API URL | `http://localhost:8100` |
| `--nucleus-token` | Nucleus 인증 토큰 | env `NUCLEUS_TOKEN` |
| `--backup-source` | 소스 라벨 (auto: local/nucleus) | 자동 감지 |
| `--skip-usd-upload` | MinIO USD 업로드 건너뛰기 (Task 2) | false |

#### Task 2: What It Does

1. **Nucleus/로컬에서 USD 다운로드** — omniverseclient SDK로 `omniverse://` 파일 다운로드
2. **Entity 식별** — Reference/Payload가 있는 Prim을 Entity로 인식, 컨테이너 Xform도 추적
3. **Override 추출** — 사용자가 변경한 속성만 추출 (Sdf Layer API)
4. **root.usda 생성** — Stage 전체 로컬 데이터를 복사하고 Reference 경로를 상대 경로로 재작성
5. **Entity USD 다운로드** — 각 Entity의 원본 에셋을 Nucleus에서 다운로드 (중복 제거)
6. **MinIO 업로드** — `backups/{timestamp}/root.usda` + `backups/{timestamp}/entities/*.usd`
7. **Iceberg 저장** — Entity 메타데이터 + Override properties를 `polaris.netai.entities` / `polaris.netai.prim_snapshots` 테이블에 저장

#### MinIO Backup Structure

```
warehouse2/backups/
└── 2026-03-29_15-40-18.375/
    ├── root.usda                      ← Stage 전체 (경로 재작성됨)
    └── entities/
        ├── jetbot.usd                 ← 원본 에셋 (Nucleus에서 다운로드)
        ├── kaya.usd
        ├── table_instanceable.usd
        ├── default_environment.usd
        └── basic_block.usd            ← Block_A + Block_B 공유
```

---

### 3. Web Dashboard (React)

`dashboard/` — React SPA (Vite + nginx). 활성 페이지:

| 페이지 | URL | Description |
|--------|-----|-------------|
| SQL Query | http://localhost:3000/query | Trino SQL 실행 인터페이스 |
| Iceberg Hub | http://localhost:3000/iceberg | Iceberg 기능 체험 (Time Travel, Schema Evolution 등) |
| Entity Diff | http://localhost:3000/entity-diff | 3-Level 드릴다운 Entity 비교 (Task 2 백업 시점 간 diff) |
| Raw Backup | http://localhost:3000/raw-backup | Raw 백업 파일 탐색기 (Task 1) |

> Congestion, Static Objects, Dynamic Objects 페이지는 레거시로 현재 워크플로에서 사용하지 않습니다.

#### Entity Diff 사용법 (Task 2)

1. **Load Backup Times** 클릭 → 시점 목록 로드 (소스 라벨 `[nucleus]`/`[local]` 표시)
2. **Time A / Time B** 선택 → **Compare** 클릭
3. **Level 1**: Entity 목록 (added/removed/changed/unchanged)
4. **Level 2**: Entity 클릭 → 내부 Prim 비교
5. **Level 3**: Prim 클릭 → JSON property diff

---

### 4. Isaac Sim Extensions

`Omniverse/omniverse-extensions/` — Isaac Sim 5.1.0 Extensions.

#### 설치

Isaac Sim Extension Manager에서 `Search Paths`에 다음 추가:
```
<repo_path>/Omniverse/omniverse-extensions
```

#### KKR.TimeTravel (`time.travel/`) — Task 3 (Time Travel Restore)

메뉴: **Tools > KKR-Tools > Time Travel**

| UI Frame | Description |
|----------|-------------|
| **Status / Log** | 작업 상태 및 로그 표시 |
| **API URL Settings** | Local (`localhost:8100`) / Docker (`lakehouse-api:8000`) 프리셋 |
| **Backup Times** | Task 2 백업 시점 목록 로드 |
| **Restore Mode** | Changes Only / Full Entity / Full All — 3가지 복원 모드 |
| **Undo** | 메모리 스냅샷 기반 되돌리기 |
| **Nucleus Reopen** | Nucleus 서버에서 Stage 재오픈 |

#### KKR.Lakehouse (`lakehouse.proto/`) — Deprecated

> 이 Extension은 더 이상 Task 1/2/3 워크플로에 사용되지 않습니다. Prim 스캔 및 USD 익스포트 기능은 실험적 구현으로 남아있으나 활성 작업에서 제외됩니다. Task 1/2는 `nucleus_pipeline/` CLI를 사용하세요.

#### 제약사항

- Isaac Sim 내부에서는 `urllib`만 사용 (외부 pip 패키지 불가)
- API URL: 환경변수 `LAKEHOUSE_API_URL` 또는 기본값 `http://lakehouse-api:8000`

---

## Data Flow

```
[Nucleus Pipeline (Task 1)]              [Nucleus Pipeline (Task 2)]
        │                                       │
        │ POST /api/v1/raw-backup/files          │ POST /api/v1/entities/backup
        │                                       │ POST /api/v1/upload-usd
        ▼                                       ▼
┌─────────────────────────────────────────────────────┐
│                 Lakehouse API (:8100)                │
├─────────────────────────────────────────────────────┤
│  Trino (:8900)  ──▶  Polaris (:8181)  ──▶  MinIO   │
│   (SQL Engine)      (REST Catalog)      (S3 :9000)  │
└─────────────────────────────────────────────────────┘
        ▲                        ▲
        │ GET /api/v1/entities/* │ fetch API
┌───────┴──────────────┐ ┌──────┴───────────┐
│ KKR.TimeTravel (Task3│ │ Dashboard (:3000) │
│ Isaac Sim Extension) │ └──────────────────┘
└──────────────────────┘
```

---

## Iceberg Table Schema

Trino 접근: catalog=`polaris`, namespace=`netai`

### `polaris.netai.entities` (Task 2)

| Column | Type | Description |
|--------|------|-------------|
| entity_id | VARCHAR | UUID |
| entity_path | VARCHAR | USD Prim 경로 (예: /World/Robots/Jetbot) |
| entity_type | VARCHAR | Prim 타입 (Xform, Mesh 등) |
| source_type | VARCHAR | reference / payload / container |
| source_asset | VARCHAR | 원본 에셋 URL |
| entity_hash | VARCHAR | SHA-256 hash (변경 감지용) |
| backup_source | VARCHAR | nucleus / local |
| backup_time | TIMESTAMP(6) | 백업 시점 |

### `polaris.netai.prim_snapshots` (Task 2)

| Column | Type | Description |
|--------|------|-------------|
| entity_path | VARCHAR | 소속 Entity 경로 |
| relative_path | VARCHAR | Entity 내 상대 경로 |
| prim_type | VARCHAR | Prim 타입 |
| properties | VARCHAR | Override 속성 (JSON) |
| prim_hash | VARCHAR | Property hash |
| backup_time | TIMESTAMP(6) | 백업 시점 |

### `polaris.netai.raw_backup_files` (Task 1)

| Column | Type | Description |
|--------|------|-------------|
| file_id | VARCHAR | UUID |
| nucleus_path | VARCHAR | 원본 Nucleus 파일 경로 |
| s3_key | VARCHAR | MinIO 저장 경로 |
| file_size | BIGINT | 파일 크기 (bytes) |
| file_hash | VARCHAR | SHA-256 hash (변경 감지용) |
| backup_time | TIMESTAMP(6) | 백업 시점 |

---

## Project Structure

```
NetAI-Digital-Twin/
├── api_service/                    # FastAPI middleware
│   ├── app/
│   │   ├── api/v1/                 # REST endpoints
│   │   ├── routers/                # Entity backup/restore routes
│   │   ├── services/               # Business logic (Iceberg, S3, Trino)
│   │   ├── schemas/                # Pydantic models
│   │   └── core/                   # Config, logging, Trino client
│   ├── tests/                      # 576 tests
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/                      # React SPA (Vite + nginx)
│   ├── src/
│   │   ├── pages/                  # 6 pages
│   │   └── components/             # Reusable UI components
│   └── Dockerfile
├── nucleus_pipeline/               # USD backup CLI tool
│   ├── main.py                     # CLI entrypoint
│   ├── usd_parser.py               # PyUSD parsing + root.usda generation
│   ├── nucleus_client.py           # Nucleus download (omniverseclient)
│   ├── lakehouse_client.py         # API calls + MinIO upload
│   ├── Dockerfile
│   └── requirements.txt
├── Omniverse/
│   └── omniverse-extensions/
│       ├── time.travel/            # KKR.TimeTravel — Task 3 (active)
│       └── lakehouse.proto/        # KKR.Lakehouse — deprecated (not used in Task 1/2/3)
├── Lakehouse/Iceberg/
│   ├── docker-compose.yml          # Stack orchestration (7 services)
│   ├── start.sh                    # Startup script
│   ├── scripts/                    # Init + verify scripts
│   └── example.env                 # Environment template
└── CLAUDE.md                       # AI assistant instructions
```

---

## Key Conventions

- `docker compose`는 반드시 `Lakehouse/Iceberg/`에서 실행
- `.env` 파일은 커밋하지 않음 (`example.env` 참조)
- 모든 컨테이너 healthcheck에 `127.0.0.1` 사용 (Tailscale DNS 간섭 방지)
- MinIO는 `MINIO_DOMAIN=minio` + Docker network alias로 virtual-hosted-style S3 접근
- Polaris `CATALOG_MANAGE_CONTENT` 권한은 컨테이너 재생성 시 재부여 필요
- Isaac Sim Extension은 **Tools > KKR-Tools** 서브메뉴에 등록

## Deployment Gotchas

- **Windows → Linux**: `git clone -b <branch>` 사용 (rsync 대신, `.gitattributes` LF 정규화 자동 적용)
- **Docker image tags**: AI 코드 생성 시 미래 날짜 태그 주의 — `:latest` 사용 권장
- **healthcheck**: docker-compose.yml의 healthcheck가 Dockerfile HEALTHCHECK를 override — 디버깅 시 둘 다 확인
- **omniverseclient DLL 충돌**: Windows에서 omniverseclient + usd-core 동시 import 불가 — subprocess 분리로 해결
- **Nucleus Pipeline Python**: Python 3.11 권장 (usd-core, omniverseclient 호환)
