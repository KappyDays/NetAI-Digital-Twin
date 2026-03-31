# Iceberg Lakehouse Deployment & Verification Guide

Headless Ubuntu 24.04 (L40S GPU) server deployment guide for the NetAI Digital Twin Iceberg Lakehouse stack.

## What to Transfer — Required Files & Folders

`NetAI-Digital-Twin/` 프로젝트 루트에는 여러 폴더가 존재하지만, **Iceberg Lakehouse 스택 배포에 필요한 파일/폴더는 아래 4개뿐**입니다.

### Must Have (서버에 반드시 필요)

```
NetAI-Digital-Twin/
├── Lakehouse/Iceberg/          # Docker Compose 스택 (진입점)
│   ├── docker-compose.yml      #   서비스 정의 (MinIO, Polaris, Trino, API, Dashboard)
│   ├── example.env             #   환경변수 템플릿 → .env로 복사
│   ├── start.sh                #   기동 스크립트
│   ├── scripts/                #   init-minio-buckets.sh, init-polaris-catalog.sh, verify-stack.sh
│   └── trino/                  #   init-catalog.sh, iceberg.properties.template
│
├── api_service/                # FastAPI 미들웨어 (docker-compose가 빌드)
│   ├── Dockerfile              #   컨테이너 빌드 파일
│   ├── app/                    #   애플리케이션 소스코드
│   ├── tests/                  #   576개 테스트
│   └── requirements.txt        #   Python 의존성
│
├── dashboard/                  # React 웹 대시보드 (docker-compose가 빌드)
│   ├── Dockerfile              #   nginx 기반 컨테이너
│   ├── src/                    #   React 컴포넌트 (히트맵, 차트 등)
│   └── package.json            #   Node.js 의존성
│
└── .gitattributes              # CRLF→LF 정규화 (Windows→Linux 이식 시 필수)
```

> **Note**: `docker-compose.yml`이 `api_service`와 `dashboard`를 상대경로(`../../api_service`, `../../dashboard`)로 참조하므로 위 3개 폴더의 상대 위치가 반드시 유지되어야 합니다.

### Optional (Omniverse Extension 사용 시)

```
NetAI-Digital-Twin/
└── Omniverse/omniverse-extensions/lakehouse.proto/
    ├── config/extension.toml   # 확장 메타데이터
    ├── KKR_Lakehouse_python/   # Extension 소스 (extension.py, ui_builder.py 등)
    └── ...
```

Isaac Sim이 설치된 환경에서만 필요합니다. API 엔드포인트 테스트만 할 경우 불필요합니다.

### Not Needed (서버에 옮기지 않아도 되는 폴더)

| Folder | Purpose | Why Not Needed |
|---|---|---|
| `.omc/` | Ouroboros AI 워크플로우 상태 | 개발 도구 전용 |
| `.playwright-mcp/` | Playwright 브라우저 테스트 | 로컬 개발 전용 |
| `CLAUDE.md` | AI 어시스턴트 설정 | 개발 도구 전용 |
| `Datacenter/` | 데이터센터 온습도 모니터링 | 별도 서브시스템 |
| `Lakehouse/DeltaLake/` | Legacy Spark 기반 레이크하우스 | Iceberg로 대체됨 |
| `TwinX/` | GPU VNC 멀티유저 환경 | 별도 서브시스템 |
| `UWB/` | UWB 실시간 측위 파이프라인 | 별도 서브시스템 |
| `extra/` | 기타 실험 파일 | 배포 불필요 |
| `references/` | 참고 자료 | 배포 불필요 |
| `scripts/` (root) | 통합 검증 스크립트 | `Lakehouse/Iceberg/scripts/`로 대체 |
| `slides/` | 프레젠테이션 슬라이드 | 배포 불필요 |
| `docker-compose.yml` (root) | 루트 Compose (Iceberg 폴더의 복사본) | `Lakehouse/Iceberg/` 것을 사용 |

### Quick Transfer Command

```bash
# 필수 4개만 전송 (최소 배포)
SERVER="user@your-server-ip"
DEST="~/NetAI-Digital-Twin"

rsync -avz --exclude='minio_data' --exclude='__pycache__' --exclude='.pytest_cache' \
  Lakehouse/Iceberg/ ${SERVER}:${DEST}/Lakehouse/Iceberg/

rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  api_service/ ${SERVER}:${DEST}/api_service/

rsync -avz --exclude='node_modules' \
  dashboard/ ${SERVER}:${DEST}/dashboard/

rsync -avz .gitattributes ${SERVER}:${DEST}/
```

---

## Prerequisites

| Component | Version | Check Command |
|---|---|---|
| Docker Engine | 24+ | `docker --version` |
| Docker Compose | v2+ | `docker compose version` |
| NVIDIA Driver | 535+ | `nvidia-smi` |
| Git | 2.x | `git --version` |

## Phase 1: Code Transfer

### Option A: Git Clone

```bash
git clone <repo-url> ~/NetAI-Digital-Twin
cd ~/NetAI-Digital-Twin
git checkout lab/exts-lakehouse
```

### Option B: Rsync from Local Machine

```bash
# Run from local Windows machine (Git Bash / WSL)
SERVER="user@your-server-ip"

rsync -avz --exclude='.omc' --exclude='minio_data' --exclude='__pycache__' \
  Lakehouse/Iceberg/ ${SERVER}:~/NetAI-Digital-Twin/Lakehouse/Iceberg/

rsync -avz --exclude='__pycache__' --exclude='.pytest_cache' \
  api_service/ ${SERVER}:~/NetAI-Digital-Twin/api_service/

rsync -avz --exclude='node_modules' \
  dashboard/ ${SERVER}:~/NetAI-Digital-Twin/dashboard/

rsync -avz \
  Omniverse/omniverse-extensions/lakehouse.proto/ \
  ${SERVER}:~/NetAI-Digital-Twin/Omniverse/omniverse-extensions/lakehouse.proto/

rsync -avz .gitattributes ${SERVER}:~/NetAI-Digital-Twin/
```

## Phase 2: Environment Configuration

```bash
cd ~/NetAI-Digital-Twin/Lakehouse/Iceberg

# Create .env from template
cp example.env .env

# Edit credentials (IMPORTANT: follow these rules)
#   MINIO_ROOT_USER     >= 5 characters
#   MINIO_ROOT_PASSWORD >= 8 characters
#   MINIO_ROOT_USER     == AWS_ACCESS_KEY_ID       (must match!)
#   MINIO_ROOT_PASSWORD == AWS_SECRET_ACCESS_KEY    (must match!)
nano .env
```

### Required .env Variables

```env
# MinIO
MINIO_ROOT_USER=admin
MINIO_ROOT_PASSWORD=admin1234

# S3 (must match MinIO credentials)
AWS_ACCESS_KEY_ID=admin
AWS_SECRET_ACCESS_KEY=admin1234
S3_BUCKET=warehouse2
S3_USD_PREFIX=usd/world_prims/

# Polaris
POLARIS_ROOT_CLIENT_ID=root
POLARIS_ROOT_CLIENT_SECRET=s3cr3t00

# Iceberg
ICEBERG_WAREHOUSE=iceberg2
ICEBERG_NAMESPACE=netai
ICEBERG_TABLE_NAME=static_prims

# Trino (optional, only if USER_DATA_PATH is used)
USER_DATA_PATH=/tmp/trino-data
```

## Phase 3: Stack Startup

```bash
# Ensure scripts are executable
chmod +x scripts/*.sh start.sh

# Build and start all services
./start.sh
# Or manually:
# docker compose up -d --build
```

### Startup Timeline

| Time | Event |
|---|---|
| 0-10s | MinIO starts, healthcheck begins |
| 10-15s | minio-init creates buckets (`warehouse2`, `usd-assets`) |
| 15-30s | Polaris starts, healthcheck begins |
| 30-40s | polaris-init creates warehouse + namespaces (`netai`, `dynamic_db`) |
| 30-60s | Trino starts, loads Iceberg catalog |
| 15-30s | lakehouse-api builds, bootstraps Iceberg schema |
| 10-20s | dashboard (nginx) starts |

**Total startup: ~60-90 seconds** until all services are healthy.

## Phase 4: Automated Stack Verification

```bash
# Wait 60-90 seconds for full initialization, then:
./scripts/verify-stack.sh --verbose
```

### Expected Output

```
============================================================
  Iceberg Lakehouse Stack — Health Verification
============================================================

[PASS] Container 'minio' is healthy
[PASS] Container 'polaris' is healthy
[PASS] Container 'trino' is healthy
[PASS] Container 'lakehouse-api' is healthy
[PASS] MinIO API is reachable at http://localhost:9000
[PASS] Polaris health endpoint is reachable
[PASS] Polaris OAuth2 token acquisition successful
[PASS] Trino is reachable and active/starting
[PASS] Trino SQL statement submission successful
[PASS] Lakehouse API root endpoint responding
[PASS] Lakehouse API /health endpoint responding
[PASS] Lakehouse API /api/v1/health endpoint responding

============================================================
  Verification Summary
============================================================
  PASS: 15  |  FAIL: 0  |  WARN: 0  |  Total: 15
============================================================
  All critical checks passed!
```

## Phase 5: Manual API Verification

### 5.1 Health Check

```bash
curl -s http://localhost:8100/health | python3 -m json.tool
```

Expected response:
```json
{
    "status": "healthy",
    "service": "lakehouse-api",
    "version": "1.0.0",
    "dependencies": {
        "minio": {"status": "healthy"},
        "polaris": {"status": "healthy"},
        "trino_iceberg": {"status": "healthy"}
    }
}
```

### 5.2 Static Prim Insertion (AC 3)

```bash
curl -s -X POST http://localhost:8100/api/v1/prims \
  -H "Content-Type: application/json" \
  -d '{
    "records": [
      {
        "prim_path": "/World/Room_A/Chair_01",
        "type": "Mesh",
        "properties": "{\"material\": \"wood\", \"color\": \"brown\"}"
      },
      {
        "prim_path": "/World/Room_A/Table_01",
        "type": "Mesh",
        "properties": "{\"material\": \"metal\", \"height\": 0.75}"
      },
      {
        "prim_path": "/World/Room_B/Camera_01",
        "type": "Camera",
        "properties": "{\"fov\": 60, \"resolution\": [1920, 1080]}"
      }
    ]
  }' | python3 -m json.tool
```

Expected:
```json
{
    "inserted": 3,
    "table": "netai.static_prims",
    "message": "Successfully inserted 3 static prim records"
}
```

### 5.3 Trino SQL Query (AC 8)

```bash
curl -s -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT space_id, prim_path, prim_type FROM iceberg.netai.static_prims LIMIT 10"}' \
  | python3 -m json.tool
```

### 5.4 Dynamic Object Ingest (AC 4)

```bash
curl -s -X POST http://localhost:8100/api/v1/dynamic/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "records": [
      {
        "object_id": "robot_01",
        "space_id": "Room_A",
        "pos_x": 1.5,
        "pos_y": 2.3,
        "pos_z": 0.0,
        "rot_x": 0.0,
        "rot_y": 0.0,
        "rot_z": 45.0,
        "properties": "{\"battery\": 85, \"speed\": 1.2}"
      }
    ]
  }' | python3 -m json.tool
```

### 5.5 USD File Upload (AC 5)

```bash
# Create a test file
echo '{"test": "usd_content"}' > /tmp/test_prim.usda

curl -s -X POST http://localhost:8100/api/v1/upload-usd \
  -F "file=@/tmp/test_prim.usda" \
  | python3 -m json.tool
```

### 5.6 Congestion Summary (AC 6 data endpoint)

```bash
curl -s http://localhost:8100/api/v1/spaces/congestion/summary \
  | python3 -m json.tool
```

### 5.7 Dashboard Access (AC 7)

```bash
# From server: check HTTP status
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/

# From local machine: SSH tunnel for browser access
ssh -L 3000:localhost:3000 -L 8100:localhost:8100 user@server-ip
# Then open http://localhost:3000 in browser
```

### 5.8 Swagger API Docs

```bash
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://localhost:8100/docs
# SSH tunnel, then open http://localhost:8100/docs in browser
```

## Phase 6: Omniverse Extension Setup

> Requires Isaac Sim installed on the server or a separate workstation.

### 6.1 Register Extension Path

In Isaac Sim:
1. **Window > Extensions**
2. Click **Settings** (gear icon)
3. Add to **Extension Search Paths**:
   ```
   /path/to/NetAI-Digital-Twin/Omniverse/omniverse-extensions/lakehouse.proto
   ```

### 6.2 Configure API URL

```bash
# If Isaac Sim runs on the same server:
export LAKEHOUSE_API_URL=http://localhost:8100

# If Isaac Sim runs on a different machine:
export LAKEHOUSE_API_URL=http://<server-ip>:8100
```

### 6.3 Extension Features

| Feature | Description |
|---|---|
| **Task 1: Export Prims** | Scans all Stage Prims → POST /api/v1/prims |
| **Task 2: Upload USD** | Exports /World children as USD → POST /api/v1/upload-usd |
| **Congestion View** | Displays space congestion summary in omni.ui panel |
| **Drilldown** | Click a space → shows per-object detail |

### 6.4 Headless Mode Note

Isaac Sim headless mode (`./isaac-sim.sh --headless`) does not render Extension UI.
To verify Extension functionality in headless mode, call the API endpoints directly
using the curl commands in Phase 5.

## Phase 7: E2E Data Round-Trip Verification

Run this sequence to verify the complete data pipeline:

```bash
#!/bin/bash
# E2E verification script
set -e
API="http://localhost:8100"

echo "=== Step 1: Insert Static Prims ==="
curl -sf -X POST ${API}/api/v1/prims \
  -H "Content-Type: application/json" \
  -d '{"records":[{"prim_path":"/World/TestSpace/Obj_01","type":"Xform","properties":"{}"}]}' \
  | python3 -m json.tool

echo "=== Step 2: Query via Trino ==="
curl -sf -X POST ${API}/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT * FROM iceberg.netai.static_prims WHERE space_id='\''TestSpace'\''"}' \
  | python3 -m json.tool

echo "=== Step 3: Ingest Dynamic Data ==="
curl -sf -X POST ${API}/api/v1/dynamic/ingest \
  -H "Content-Type: application/json" \
  -d '{"records":[{"object_id":"sensor_01","space_id":"TestSpace","pos_x":0,"pos_y":0,"pos_z":0}]}' \
  | python3 -m json.tool

echo "=== Step 4: Check Congestion ==="
curl -sf ${API}/api/v1/spaces/congestion/summary | python3 -m json.tool

echo "=== Step 5: Dashboard Health ==="
curl -sf -o /dev/null -w "Dashboard: HTTP %{http_code}\n" http://localhost:3000/

echo "=== E2E Round-Trip COMPLETE ==="
```

## Port Reference

| Service | Port | Protocol | Purpose |
|---|---|---|---|
| MinIO API | 9000 | HTTP | S3-compatible object storage |
| MinIO Console | 9001 | HTTP | Web management UI |
| Polaris REST | 8181 | HTTP | Iceberg REST Catalog API |
| Polaris Health | 8182 | HTTP | Management / health endpoint |
| Trino | 8900 | HTTP | SQL query engine (mapped from 8080) |
| Lakehouse API | 8100 | HTTP | FastAPI middleware (mapped from 8000) |
| Dashboard | 3000 | HTTP | React web dashboard (nginx) |

## Troubleshooting

### Services not starting

```bash
# Check container status
docker compose ps

# Check logs for a specific service
docker compose logs polaris
docker compose logs lakehouse-api
docker compose logs trino
```

### Credential mismatch errors

Ensure in `.env`:
- `MINIO_ROOT_USER` == `AWS_ACCESS_KEY_ID`
- `MINIO_ROOT_PASSWORD` == `AWS_SECRET_ACCESS_KEY`

### CRLF issues (if transferred from Windows without git)

```bash
# Fix line endings on all shell scripts
find . -name "*.sh" -exec sed -i 's/\r$//' {} +
find . -name "*.properties" -exec sed -i 's/\r$//' {} +
```

### Polaris not creating warehouse

```bash
# Check Polaris health
curl -s http://localhost:8182/q/health

# Re-run init manually
docker compose restart polaris-init
docker compose logs polaris-init
```

### Trino cannot find Iceberg catalog

```bash
# Check catalog properties were rendered
docker exec trino cat /etc/trino/catalog/iceberg.properties

# Restart Trino if needed
docker compose restart trino
```
