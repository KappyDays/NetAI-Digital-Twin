# NetAI-Digital-Twin

Network AI Digital Twin 플랫폼 — **Iceberg Lakehouse** 데이터 인프라 위에 **NVIDIA Omniverse/Isaac Sim** 기반 Digital Twin을 구축하고, **Nucleus Pipeline**으로 Stage 백업/복원/타임트래블을 제공합니다.

## Architecture

```
                        ┌─────────────────────┐
                        │  Isaac Sim (Extension)│
                        │  lakehouse.proto     │
                        └──────────┬──────────┘
                                   │ HTTP (urllib)
                                   ▼
┌──────────────┐    ┌──────────────────────────┐    ┌──────────────────┐
│ Nucleus      │    │   Lakehouse API (FastAPI) │    │  Web Dashboard   │
│ Pipeline     │───▶│        :8100              │◀───│  (React) :3000   │
│ (CLI/Python) │    └──────┬───────┬───────┬────┘    └──────────────────┘
└──────────────┘           │       │       │
                    ┌──────▼──┐ ┌──▼──┐ ┌──▼──────────┐
                    │  Trino  │ │MinIO│ │   Polaris    │
                    │  :8900  │ │:9000│ │   :8181      │
                    │  (SQL)  │ │(S3) │ │ (REST Catalog)│
                    └─────────┘ └─────┘ └──────────────┘
                         │         │           │
                         └─────────┴───────────┘
                            Iceberg Tables
                          (Parquet on MinIO)
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
| `POST` | `/api/v1/prims` | Static Prim records 삽입 (Iceberg) |
| `POST` | `/api/v1/dynamic/ingest` | Dynamic object IoT 데이터 삽입 |
| `POST` | `/api/v1/upload-usd` | USD 파일 MinIO 업로드 (s3_key 지정 가능) |
| `GET` | `/api/v1/download-usd?s3_key=...` | MinIO에서 USD 파일 다운로드 |
| `POST` | `/api/v1/query` | Ad-hoc Trino SQL 실행 |
| `GET` | `/api/v1/spaces/congestion/summary` | 공간 혼잡도 집계 |
| `GET` | `/api/v1/dynamic/query/latest` | 최신 dynamic object 상태 |

#### Entity Backup/Restore/Diff

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/entities/backup` | Entity + Prim Snapshot 일괄 저장 |
| `GET` | `/api/v1/entities/backup-times` | 백업 시점 목록 (backup_source 포함) |
| `GET` | `/api/v1/entities/list?backup_time=...` | 특정 시점의 Entity 목록 |
| `GET` | `/api/v1/entities/diff?time_a=...&time_b=...` | 두 시점 Entity 비교 |
| `GET` | `/api/v1/entities/{path}/prim-diff?time_a=...&time_b=...` | Entity 내부 Prim 비교 |
| `GET` | `/api/v1/entities/{path}/restore?backup_time=...` | Entity 복원 데이터 조회 |

#### Test

```bash
cd api_service
python -m pytest tests/ -v    # 576 tests, ~45s
```

---

### 2. Nucleus Pipeline (CLI)

`nucleus_pipeline/` — Isaac Sim 없이 Nucleus/로컬 USD 파일을 파싱하여 Iceberg에 백업하고, MinIO에 USD 파일을 저장하는 독립 CLI 도구.

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

#### Usage

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
| `--local-path` | 로컬 USD/USDA 파일 경로 | — |
| `--nucleus-path` | Nucleus 경로 (omniverse://...) | — |
| `--api-url` | Lakehouse API URL | `http://localhost:8100` |
| `--nucleus-token` | Nucleus 인증 토큰 | env `NUCLEUS_TOKEN` |
| `--backup-source` | 소스 라벨 (auto: local/nucleus) | 자동 감지 |
| `--skip-usd-upload` | MinIO USD 업로드 건너뛰기 | false |

#### What It Does

1. **Nucleus/로컬에서 USD 다운로드** — omniverseclient SDK로 `omniverse://` 파일 다운로드
2. **Entity 식별** — Reference/Payload가 있는 Prim을 Entity로 인식, 컨테이너 Xform도 추적
3. **Override 추출** — 사용자가 변경한 속성만 추출 (Sdf Layer API)
4. **root.usda 생성** — Stage 전체 로컬 데이터를 복사하고 Reference 경로를 상대 경로로 재작성
5. **Entity USD 다운로드** — 각 Entity의 원본 에셋을 Nucleus에서 다운로드 (중복 제거)
6. **MinIO 업로드** — `backups/{timestamp}/root.usda` + `backups/{timestamp}/entities/*.usd`
7. **Iceberg 저장** — Entity 메타데이터 + Override properties를 Iceberg 테이블에 저장

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

#### Time Travel (타임트래블)

```bash
# 1. 백업 시점 조회
curl http://localhost:8100/api/v1/entities/backup-times

# 2. 특정 시점의 Entity override SQL 쿼리
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT entity_path, properties FROM iceberg.static_db.prim_snapshots WHERE backup_time = TIMESTAMP '\''2026-03-29 15:40:18.375'\'' ORDER BY entity_path"}'

# 3. MinIO에서 복원용 root.usda 다운로드
curl -o restored.usda "http://localhost:8100/api/v1/download-usd?s3_key=backups/2026-03-29_15-40-18.375/root.usda"

# 4. Isaac Sim에서 Open → 해당 시점의 Stage 재현
```

---

### 3. Web Dashboard (React)

`dashboard/` — 6개 페이지로 구성된 React SPA (Vite + nginx).

| 페이지 | URL | Description |
|--------|-----|-------------|
| Congestion | http://localhost:3000/ | 공간 혼잡도 히트맵 + KPI + 시계열 차트 |
| Static Objects | http://localhost:3000/static | Static Prim 데이터 브라우저 |
| Dynamic Objects | http://localhost:3000/dynamic | Dynamic 센서 데이터 테이블 |
| SQL Query | http://localhost:3000/query | Trino SQL 실행 인터페이스 |
| Iceberg Hub | http://localhost:3000/iceberg | Iceberg 기능 체험 (Time Travel, Schema Evolution 등) |
| Entity Diff | http://localhost:3000/entity-diff | 3-Level 드릴다운 Entity 비교 (백업 시점 간 diff) |

#### Entity Diff 사용법

1. **Load Backup Times** 클릭 → 시점 목록 로드 (소스 라벨 `[extension]`/`[nucleus]`/`[local]` 표시)
2. **Time A / Time B** 선택 → **Compare** 클릭
3. **Level 1**: Entity 목록 (added/removed/changed/unchanged)
4. **Level 2**: Entity 클릭 → 내부 Prim 비교
5. **Level 3**: Prim 클릭 → JSON property diff

> 교차 소스 비교 시 경고: Extension과 Nucleus/Local 백업은 속성 추출 방식이 달라 비교 결과가 부정확할 수 있습니다.

---

### 4. Isaac Sim Extension

`Omniverse/omniverse-extensions/lakehouse.proto/` — Isaac Sim에서 실행되는 Extension.

#### 설치

Isaac Sim Extension Manager에서 `Search Paths`에 다음 추가:
```
<repo_path>/Omniverse/omniverse-extensions
```

메뉴: **Tools > KKR-Tools > Lakehouse Proto**

#### 기능

| UI Frame | Description |
|----------|-------------|
| **Status / Log** | 작업 상태 및 로그 표시 |
| **API Middleware Settings** | Lakehouse API URL 설정 |
| **Stage Management** | 테스트용 Stage 생성 (Setup Stage: Grid, Table, Jetbot, Kaya, Block_A, Block_B) |
| **Entity Backup** | Entity 단위 백업 — Override 추출 + Hash 계산 + Iceberg 저장 (backup_source="extension") |
| **Entity Restore** | 백업 시점 로드 → Entity 목록 조회 → 선택한 Entity를 Stage에 복원 (Reference + Override 적용) |
| **Dynamic IoT Test** | 동적 IoT 테스트 데이터 생성 (샘플 센서 데이터 → Iceberg) |

#### 제약사항

- Isaac Sim 내부에서는 `urllib`만 사용 (외부 pip 패키지 불가)
- API URL: 환경변수 `LAKEHOUSE_API_URL` 또는 기본값 `http://lakehouse-api:8000`

---

## Data Flow

```
[Isaac Sim Extension]                    [Nucleus Pipeline]
        │                                       │
        │ POST /api/v1/prims                     │ POST /api/v1/entities/backup
        │ POST /api/v1/upload-usd                │ POST /api/v1/upload-usd (s3_key)
        ▼                                       ▼
┌─────────────────────────────────────────────────────┐
│                 Lakehouse API (:8100)                │
├─────────────────────────────────────────────────────┤
│  Trino (:8900)  ──▶  Polaris (:8181)  ──▶  MinIO   │
│   (SQL Engine)      (REST Catalog)      (S3 :9000)  │
└─────────────────────────────────────────────────────┘
        ▲
        │ fetch API
┌───────┴──────────┐
│ Dashboard (:3000)│
└──────────────────┘
```

---

## Iceberg Table Schema

### `iceberg.static_db.entities`

| Column | Type | Description |
|--------|------|-------------|
| entity_id | VARCHAR | UUID |
| entity_path | VARCHAR | USD Prim 경로 (예: /World/Robots/Jetbot) |
| entity_type | VARCHAR | Prim 타입 (Xform, Mesh 등) |
| source_type | VARCHAR | reference / payload / container |
| source_asset | VARCHAR | 원본 에셋 URL |
| entity_hash | VARCHAR | SHA-256 hash (변경 감지용) |
| backup_source | VARCHAR | extension / nucleus / local |
| backup_time | TIMESTAMP(6) | 백업 시점 |

### `iceberg.static_db.prim_snapshots`

| Column | Type | Description |
|--------|------|-------------|
| entity_path | VARCHAR | 소속 Entity 경로 |
| relative_path | VARCHAR | Entity 내 상대 경로 |
| prim_type | VARCHAR | Prim 타입 |
| properties | VARCHAR | Override 속성 (JSON) |
| prim_hash | VARCHAR | Property hash |
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
│       └── lakehouse.proto/        # Isaac Sim extension
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
