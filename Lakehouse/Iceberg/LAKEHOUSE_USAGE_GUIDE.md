# Lakehouse 사용 가이드

> 본인 참고용 치트시트. Iceberg + Trino + Polaris + MinIO 기반 Lakehouse 스택의 아키텍처, 접근 방법, 유스케이스별 워크플로우를 정리.

---

## 1. 아키텍처 개요

### 컴포넌트 역할

| 컴포넌트 | 역할 | 포트 | 한줄 설명 |
|----------|------|------|----------|
| **MinIO** | S3 호환 오브젝트 스토리지 | 9000 (API), 9001 (Console) | Iceberg 테이블 데이터 + USD 파일 저장소 |
| **Polaris** | Iceberg REST 카탈로그 | 8181 (REST), 8182 (Health) | 테이블 메타데이터 관리, OAuth2 인증 |
| **Trino** | 분산 SQL 쿼리 엔진 | 8900 (외부, 내부 8080) | Iceberg 테이블에 SQL로 접근 |
| **Lakehouse API** | FastAPI 미들웨어 | 8100 (외부, 내부 8000) | Isaac Sim ↔ Iceberg 브릿지, REST 엔드포인트 제공 |
| **Dashboard** | React SPA + nginx | 3000 | 혼잡도 히트맵, 시계열 차트, SQL 인터페이스 |
| **minio-init** | 버킷 초기화 (one-shot) | — | warehouse2, usd-assets 버킷 자동 생성 |
| **polaris-init** | 카탈로그 초기화 (one-shot) | — | warehouse, namespace, 권한 자동 설정 |

### 데이터 흐름

```
Isaac Sim Extension
    │
    ▼
Lakehouse API (:8100) ──────────► MinIO (:9000)
    │                               ▲  S3 저장 (Iceberg 데이터 + USD 파일)
    │                               │
    ▼                               │
Trino (:8900) ◄──── Polaris (:8181) ┘
    │                  메타데이터 관리
    ▼
SQL 쿼리 결과 반환

Dashboard (:3000) ──► nginx ──► Lakehouse API (:8100) ──► 같은 흐름
```

### 핵심 개념

- **Iceberg Table**: Parquet 파일 + 메타데이터로 구성된 테이블. MinIO에 데이터, Polaris에 메타데이터 저장
- **Warehouse**: `iceberg2` — Polaris에서 관리하는 카탈로그 단위
- **Namespace**: `netai` (정적 Prim), `dynamic_db` (동적 IoT) — 테이블 그룹
- **Static Prims**: USD Stage의 고정 구조물 정보 (`netai.static_prims` 테이블)
- **Dynamic Objects**: 시간에 따라 위치가 변하는 객체 (`dynamic_<object_id>` 개별 테이블)

---

## 2. 접근 방법 총정리

### 방법 1: Trino CLI (docker exec)

**가장 직접적인 SQL 접근.** 컨테이너 내부에서 Trino CLI 실행.

```bash
# Trino CLI 접속
docker exec -it trino trino

# 기본 명령
SHOW CATALOGS;
SHOW SCHEMAS FROM iceberg;
SHOW TABLES FROM iceberg.netai;

# 데이터 조회
SELECT * FROM iceberg.netai.static_prims LIMIT 10;
SELECT space_id, COUNT(*) AS cnt FROM iceberg.netai.static_prims GROUP BY space_id;
SELECT DISTINCT type FROM iceberg.netai.static_prims;

# Dynamic 테이블 목록
SHOW TABLES FROM iceberg.dynamic_db;

# Dynamic 객체 조회
SELECT * FROM iceberg.dynamic_db.dynamic_worker_01 ORDER BY timestamp DESC LIMIT 5;

# 종료
quit;
```

**언제 사용?** 빠른 SQL 확인, 디버깅, 테이블 구조 탐색

---

### 방법 2: Trino Web UI

**URL:** http://localhost:8900

**기능:**
- 실행 중인 쿼리 모니터링
- 쿼리 실행 계획(Plan) 확인
- 클러스터 리소스 사용량
- 과거 쿼리 이력

**언제 사용?** 쿼리 성능 분석, 느린 쿼리 디버깅, 클러스터 상태 확인

> 주의: Trino Web UI는 쿼리 **실행** 기능이 없음. 모니터링 전용.

---

### 방법 3: Swagger UI (API 문서 + 테스트)

**URL:** http://localhost:8100/docs

**기능:**
- 전체 API 엔드포인트 목록 확인
- "Try it out" 버튼으로 실시간 API 호출 테스트
- Request/Response 스키마 확인
- 파라미터 검증

**주요 사용 예시:**
1. `POST /api/v1/query` → SQL 쿼리 실행
2. `POST /api/v1/prims` → Prim 데이터 삽입
3. `GET /api/v1/spaces/congestion/summary` → 혼잡도 조회
4. `POST /api/v1/upload-usd` → USD 파일 업로드

**언제 사용?** API 동작 확인, 새 엔드포인트 테스트, 스키마 참조

---

### 방법 4: Dashboard (Web UI)

**URL:** http://localhost:3000

**페이지:**
- **Congestion** — 공간별 혼잡도 히트맵 + 시계열 차트
- **Static Objects** — 정적 Prim 브라우저
- **Dynamic Objects** — 동적 객체 센서 데이터 테이블
- **SQL Query** — 직접 Trino SQL 실행 + 결과 테이블 표시

**SQL Query 페이지 사용법:**
```sql
-- 직접 입력하고 "Run Query" 클릭
SELECT prim_path, type, space_id FROM iceberg.netai.static_prims LIMIT 20
```

**프리셋 버튼:** `List static spaces`, `Show all schemas`, `Show tables in netai`, `Recent dynamic data`

**언제 사용?** 시각적 데이터 탐색, 혼잡도 모니터링, 빠른 SQL 실행

---

### 방법 5: MinIO Console

**URL:** http://localhost:9001
**로그인:** admin / admin1234 (`.env` 기준)

**기능:**
- 버킷 브라우저 (warehouse2, usd-assets)
- 파일 업로드/다운로드
- 오브젝트 메타데이터 확인
- 버킷 정책 관리

**주요 확인 사항:**
- `warehouse2/netai/` → Iceberg 테이블 Parquet 파일들
- `warehouse2/usd/` → 업로드된 USD 파일들
- `usd-assets/` → 별도 USD 에셋 저장소

**언제 사용?** S3 데이터 직접 확인, 파일 수동 관리, 버킷 상태 점검

---

### 방법 6: REST API (curl / Postman / Python)

#### curl 예시

```bash
# 헬스체크
curl.exe http://localhost:8100/health

# Static Prim 삽입
curl.exe -X POST http://localhost:8100/api/v1/prims `
  -H "Content-Type: application/json" `
  -d '{\"records\":[{\"prim_path\":\"/World/Room/Chair\",\"type\":\"Mesh\",\"properties\":\"{}\"}]}'

# SQL 쿼리 실행
curl.exe -X POST http://localhost:8100/api/v1/query `
  -H "Content-Type: application/json" `
  -d '{\"sql\":\"SELECT * FROM iceberg.netai.static_prims LIMIT 5\"}'

# Dynamic 데이터 삽입
curl.exe -X POST http://localhost:8100/api/v1/dynamic/ingest `
  -H "Content-Type: application/json" `
  -d '{\"records\":[{\"object_id\":\"worker_01\",\"pos_x\":1.0,\"pos_y\":2.0,\"pos_z\":0.0,\"speed\":0.5,\"space_id\":\"RoomA\"}]}'

# 혼잡도 조회
curl.exe http://localhost:8100/api/v1/spaces/congestion/summary

# Dynamic 객체 최신 상태
curl.exe "http://localhost:8100/api/v1/dynamic/query/latest?limit=100"

# USD 파일 업로드
curl.exe -X POST http://localhost:8100/api/v1/upload-usd -F "file=@model.usda"
```

> **PowerShell 주의:** `curl`이 `Invoke-WebRequest` alias. 반드시 `curl.exe` 사용!

#### Python 예시

```python
import urllib.request
import json

API_BASE = "http://localhost:8100"

# SQL 쿼리
req = urllib.request.Request(
    f"{API_BASE}/api/v1/query",
    data=json.dumps({"sql": "SELECT count(*) FROM iceberg.netai.static_prims"}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
    print(result)
```

**언제 사용?** 자동화 스크립트, CI/CD 파이프라인, 프로그래밍 방식 접근

---

### 방법 7: Isaac Sim Extension

**설정:** `LAKEHOUSE_API_URL=http://localhost:8100` (Extension UI에서도 변경 가능)

**기능:**
- **lakehouse.proto**: Task 1 (Prim 스캔→Iceberg), Task 2 (USD export→S3)
- **stagegraph.viewer**: Stage 계층 트리뷰 + Iceberg diff
- **dynamic.tracker**: 궤적 3D 오버레이
- **space.heatmap**: 혼잡도 뷰포트 히트맵

**API 호출 흐름:**
```
Extension UI 버튼 → urllib HTTP → Lakehouse API (:8100) → Trino/MinIO → 응답
```

**언제 사용?** Isaac Sim에서 직접 데이터 관리, 시각화

---

### 방법 8: Polaris API (직접 접근 — 고급)

```bash
# OAuth2 토큰 발급
TOKEN=$(curl.exe -s -X POST http://localhost:8181/api/catalog/v1/oauth/tokens \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=root&client_secret=s3cr3t00&scope=PRINCIPAL_ROLE:ALL" \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Warehouse 목록
curl.exe -H "Authorization: Bearer $TOKEN" http://localhost:8181/api/management/v1/catalogs

# Namespace 목록
curl.exe -H "Authorization: Bearer $TOKEN" \
  http://localhost:8181/api/catalog/v1/iceberg2/namespaces
```

**언제 사용?** 카탈로그 메타데이터 직접 관리, 디버깅, 권한 설정

---

## 3. 유스케이스별 워크플로우

### WF1: 데이터 삽입 (Static Prim)

```
[Isaac Sim에서 씬 로드]
    │
    ▼
[lakehouse.proto Extension → Task 1 클릭]
    │
    ▼ POST /api/v1/prims
    │
[Lakehouse API → PyIceberg → Polaris → MinIO]
    │
    ▼
[확인] Swagger UI → POST /api/v1/query
       SQL: SELECT * FROM iceberg.netai.static_prims LIMIT 10
```

**수동 삽입 (curl):**
```bash
curl.exe -X POST http://localhost:8100/api/v1/prims \
  -H "Content-Type: application/json" \
  -d '{"records":[{"prim_path":"/World/Lab/Desk","type":"Mesh","properties":"{}"}]}'
```

---

### WF2: 데이터 조회 및 분석

**방법 A: Dashboard SQL 페이지**
1. http://localhost:3000 → SQL Query 메뉴
2. SQL 입력: `SELECT space_id, COUNT(*) as cnt FROM iceberg.netai.static_prims GROUP BY space_id`
3. Run Query 클릭 → 결과 테이블

**방법 B: Trino CLI**
```bash
docker exec -it trino trino --execute \
  "SELECT type, COUNT(*) as cnt FROM iceberg.netai.static_prims GROUP BY type ORDER BY cnt DESC"
```

**방법 C: API**
```bash
curl.exe -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql":"SELECT space_id, type, COUNT(*) as cnt FROM iceberg.netai.static_prims GROUP BY space_id, type"}'
```

---

### WF3: Dynamic 객체 모니터링

```
[IoT 센서/시뮬레이션]
    │
    ▼ POST /api/v1/dynamic/ingest
    │
[Lakehouse API → per-object Iceberg 테이블 자동 생성]
    │
    ▼
[모니터링]
  ├─ Dashboard (:3000) → Congestion 페이지 (실시간 히트맵)
  ├─ API: GET /api/v1/dynamic/query/latest (최신 상태)
  ├─ API: POST /api/v1/dynamic/query/trajectory (궤적 조회)
  └─ Isaac Sim: dynamic.tracker Extension (3D 궤적 오버레이)
```

**샘플 데이터 삽입:**
```bash
curl.exe -X POST http://localhost:8100/api/v1/dynamic/ingest \
  -H "Content-Type: application/json" \
  -d '{"records":[{"object_id":"robot_01","pos_x":3.0,"pos_y":5.0,"pos_z":0.0,"speed":1.2,"space_id":"Lab"}]}'
```

**궤적 조회:**
```bash
curl.exe -X POST http://localhost:8100/api/v1/dynamic/query/trajectory \
  -H "Content-Type: application/json" \
  -d '{"object_id":"robot_01","start_time":"2026-03-23T00:00:00","end_time":"2026-03-24T23:59:59"}'
```

---

### WF4: USD 파일 관리

```
[Isaac Sim에서 씬 로드]
    │
    ▼
[lakehouse.proto Extension → Task 2 클릭]
    │
    ▼ POST /api/v1/upload-usd (multipart form)
    │
[Lakehouse API → MinIO warehouse2/usd/world_prims/]
    │
    ▼
[확인] MinIO Console (:9001) → warehouse2 버킷 → usd/ 폴더
```

**수동 업로드:**
```bash
curl.exe -X POST http://localhost:8100/api/v1/upload-usd -F "file=@my_model.usda"
```

---

### WF5: 혼잡도 분석

```
[Dynamic 데이터가 쌓인 상태에서]
    │
    ▼
[접근 방법 선택]
  ├─ Dashboard (:3000) Congestion 페이지 → 히트맵 + 시계열 차트
  ├─ Isaac Sim space.heatmap Extension → 뷰포트 오버레이
  ├─ API: GET /api/v1/spaces/congestion/summary → JSON 응답
  └─ API: GET /api/v1/congestion/grid → 2D 그리드 데이터
```

**API 예시:**
```bash
# Space별 혼잡도 요약
curl.exe http://localhost:8100/api/v1/spaces/congestion/summary

# 2D 그리드 히트맵 데이터
curl.exe "http://localhost:8100/api/v1/congestion/grid?rows=20&cols=20&x_min=-50&x_max=50&y_min=-50&y_max=50"
```

---

## 4. 환경변수 & 인증 정보

| 변수 | 값 (example.env) | 용도 |
|------|-------------------|------|
| `MINIO_ROOT_USER` | admin | MinIO 로그인 + S3 access key |
| `MINIO_ROOT_PASSWORD` | admin1234 | MinIO 비밀번호 + S3 secret key |
| `AWS_ACCESS_KEY_ID` | admin | **= MINIO_ROOT_USER 동일해야 함** |
| `AWS_SECRET_ACCESS_KEY` | admin1234 | **= MINIO_ROOT_PASSWORD 동일해야 함** |
| `POLARIS_ROOT_CLIENT_ID` | root | Polaris OAuth2 클라이언트 ID |
| `POLARIS_ROOT_CLIENT_SECRET` | s3cr3t00 | Polaris OAuth2 시크릿 |
| `ICEBERG_WAREHOUSE` | iceberg2 | Polaris 카탈로그 이름 |
| `ICEBERG_NAMESPACE` | netai | 정적 데이터 namespace |
| `S3_BUCKET` | warehouse2 | 주 Iceberg 데이터 버킷 |
| `S3_USD_PREFIX` | usd/world_prims/ | USD 업로드 경로 prefix |

> **핵심 규칙:** `MINIO_ROOT_USER/PASSWORD` = `AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY` 반드시 일치!

---

## 5. 주요 API 엔드포인트 레퍼런스

### Static (정적 Prim)

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| POST | `/api/v1/prims` | Prim 배치 삽입 |
| GET | `/api/v1/static/prims` | Prim 조회 (space_id, type 필터) |
| GET | `/api/v1/static/spaces` | Space 목록 + 통계 |
| GET | `/api/v1/static/types` | 타입별 분포 |
| GET | `/api/v1/static/count` | 전체 카운트 |

### Dynamic (동적 객체)

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| POST | `/api/v1/dynamic/ingest` | 센서 데이터 삽입 |
| GET | `/api/v1/dynamic/tables` | 동적 테이블 목록 (list[str]) |
| GET | `/api/v1/dynamic/query/latest` | 최신 상태 조회 |
| POST | `/api/v1/dynamic/query/trajectory` | 궤적 조회 (시간 범위) |

### Congestion (혼잡도)

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| GET | `/api/v1/spaces/congestion/summary` | Space별 혼잡도 요약 |
| GET | `/api/v1/congestion/grid` | 2D 그리드 히트맵 |
| GET | `/api/v1/congestion/timeseries` | 시계열 혼잡도 |

### 기타

| Method | 엔드포인트 | 설명 |
|--------|-----------|------|
| POST | `/api/v1/query` | 임의 Trino SQL 실행 |
| POST | `/api/v1/upload-usd` | USD 파일 업로드 (multipart) |
| GET | `/health` | 전체 스택 헬스체크 |
| GET | `/docs` | Swagger UI |

---

## 6. 사용 환경 정리

### "Lakehouse를 어떤 환경에서 사용하나?"

| 사용 환경 | 접근 방법 | 주 용도 |
|----------|----------|---------|
| **웹 브라우저** | Dashboard (:3000) | 시각적 모니터링, SQL 실행 |
| **웹 브라우저** | Swagger UI (:8100/docs) | API 테스트, 스키마 확인 |
| **웹 브라우저** | MinIO Console (:9001) | S3 파일 브라우징 |
| **웹 브라우저** | Trino Web UI (:8900) | 쿼리 모니터링 |
| **터미널 (CLI)** | `docker exec -it trino trino` | 직접 SQL 실행 |
| **터미널 (CLI)** | `curl.exe` / `Invoke-RestMethod` | API 호출, 자동화 |
| **Python 스크립트** | `urllib` / `requests` | 프로그래밍 방식 접근 |
| **Isaac Sim** | Extension UI | 시뮬레이션 ↔ Lakehouse 연동 |
| **BI 도구 (향후)** | Trino JDBC (port 8900) | Superset, Tableau 등 연결 가능 |

### 정리: 실제 사용 시나리오별 최적 환경

| 시나리오 | 최적 환경 | 이유 |
|----------|----------|------|
| "테이블에 뭐가 있지?" | Trino CLI 또는 Dashboard SQL | 가장 빠른 SQL 접근 |
| "API가 제대로 동작하나?" | Swagger UI | Try-it-out으로 즉시 테스트 |
| "데이터를 프로그래밍으로 넣고 싶어" | curl / Python | 자동화 가능 |
| "S3에 파일이 잘 올라갔나?" | MinIO Console | 시각적 파일 브라우저 |
| "실시간 혼잡도를 보고 싶어" | Dashboard 또는 Isaac Sim Extension | 시각화 최적화 |
| "Isaac Sim 씬을 Lakehouse에 저장" | lakehouse.proto Extension | 원클릭 export |
| "느린 쿼리를 분석하고 싶어" | Trino Web UI | 실행 계획, 리소스 모니터링 |

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| API 401 Unauthorized | Polaris `CATALOG_MANAGE_CONTENT` 권한 없음 | `docker restart polaris-init` |
| MinIO 연결 실패 | 컨테이너 미시작 | `docker compose ps` → `docker compose up -d minio` |
| Trino 쿼리 에러 "Table not found" | 테이블 미생성 또는 Polaris 연결 실패 | `SHOW SCHEMAS FROM iceberg;` 로 확인 |
| Dashboard에 데이터 없음 (0 spaces) | Dynamic 데이터 미삽입 | `POST /api/v1/dynamic/ingest`로 데이터 넣기 |
| PowerShell에서 curl 에러 | `curl` = `Invoke-WebRequest` alias | **`curl.exe`** 사용 (`.exe` 필수) |
| 컨테이너 healthcheck 실패 | Tailscale VPN → localhost DNS 충돌 | healthcheck에 `127.0.0.1` 사용 (이미 적용됨) |
| Polaris 재시작 후 권한 없음 | 컨테이너 재생성 시 권한 초기화됨 | `docker restart polaris-init` |
| Trino "starting" 상태 지속 | Polaris가 아직 ready 아님 | 30-60초 대기 후 재확인 |

---

## 8. 빠른 명령어 모음

```bash
# 스택 시작
cd Lakehouse/Iceberg && docker compose up -d --build

# 스택 상태 확인
docker compose ps

# 전체 검증
./scripts/verify-stack.sh --verbose

# Trino CLI 접속
docker exec -it trino trino

# 스택 중지
docker compose down

# 로그 확인
docker compose logs lakehouse-api --tail 50
docker compose logs trino --tail 50

# 컨테이너 재시작
docker compose restart polaris-init  # 권한 재부여
docker compose restart lakehouse-api # API 재시작
```

---

*마지막 업데이트: 2026-03-24*
