# Lakehouse 스택 테스트 절차 & 튜토리얼

> **대상**: NetAI-Digital-Twin Iceberg Lakehouse 스택
> **검증일**: 2026-03-25
> **결과**: 27/27 PASS (E2E 자동 테스트)

---

## 1. 스택 개요

```
┌─────────────┐    ┌──────────┐    ┌───────────┐    ┌──────────────┐    ┌────────────┐
│ MinIO (S3)  │◄───│ Polaris  │◄───│  Trino    │◄───│ Lakehouse    │◄───│ Dashboard  │
│ :9000/:9001 │    │ :8181    │    │ :8900     │    │ API :8100    │    │ :3000      │
│ 오브젝트 저장│    │ REST 카탈로그│   │ SQL 엔진  │    │ FastAPI 미들웨어│   │ React SPA  │
└─────────────┘    └──────────┘    └───────────┘    └──────────────┘    └────────────┘
```

| 서비스 | 포트 | 용도 | 헬스체크 URL |
|--------|------|------|-------------|
| MinIO | 9000/9001 | S3 호환 오브젝트 스토리지 | `http://localhost:9000/minio/health/live` |
| Polaris | 8181/8182 | Apache Iceberg REST 카탈로그 | `http://localhost:8182/q/health` |
| Trino | 8900 | 분산 SQL 쿼리 엔진 | Trino UI: `http://localhost:8900` |
| Lakehouse API | 8100 | FastAPI 미들웨어 | `http://localhost:8100/api/v1/health` |
| Dashboard | 3000 | React 웹 대시보드 | `http://localhost:3000` |

---

## 2. 스택 시작

```bash
cd Lakehouse/Iceberg

# 1. 환경 변수 설정
cp example.env .env    # 필요 시 MinIO 인증정보 수정

# 2. 스택 기동
docker compose up -d --build

# 3. 상태 확인 (모든 서비스 healthy 될 때까지 ~60초)
docker compose ps
```

---

## 3. 인프라 검증 (수동)

### 3.1 MinIO 확인
```bash
# 헬스체크
curl http://localhost:9000/minio/health/live
# → HTTP 200 (빈 응답)

# 웹 콘솔
# 브라우저: http://localhost:9001
# 로그인: .env의 MINIO_ROOT_USER / MINIO_ROOT_PASSWORD
```

### 3.2 Polaris 카탈로그 확인
```bash
curl http://localhost:8182/q/health
# → {"status":"UP","checks":[...]}
```

### 3.3 Lakehouse API 확인
```bash
curl http://localhost:8100/api/v1/health
# → {"status":"healthy"}

# 의존성 포함 상세 헬스체크
curl http://localhost:8100/health
# → {"status":"healthy","dependencies":{"minio":{"status":"healthy"},"polaris":{"status":"healthy"},"trino_iceberg":{"status":"healthy"}}}
```

### 3.4 Dashboard 확인
```bash
curl -s http://localhost:3000/ | head -1
# → <!DOCTYPE html>

# 브라우저: http://localhost:3000
```

---

## 4. Trino SQL 엔진 검증

### 4.1 스키마 & 테이블 조회
```bash
# Lakehouse API를 통한 Trino SQL 실행
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SHOW SCHEMAS FROM iceberg"}'
# → netai, dynamic_db, information_schema, system

curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SHOW TABLES FROM iceberg.netai"}'
# → static_prims
```

### 4.2 테이블 구조 확인
```bash
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "DESCRIBE iceberg.netai.static_prims"}'
# → prim_path(VARCHAR), type(VARCHAR), properties(VARCHAR), space_id(VARCHAR), ingested_at(TIMESTAMP)
```

---

## 5. Iceberg 10대 기능 테스트

### 5.1 Time Travel (스냅샷 시간여행)

```bash
# 스냅샷 목록 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM iceberg.netai.\"static_prims$snapshots\" ORDER BY committed_at DESC"}'

# 특정 시점 데이터 조회 (타임스탬프)
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM iceberg.netai.static_prims FOR TIMESTAMP AS OF TIMESTAMP '\''2026-03-25 02:01:47'\'' LIMIT 10"}'

# 특정 스냅샷 ID로 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM iceberg.netai.static_prims FOR VERSION AS OF 936368314663528761 LIMIT 10"}'
```

> **Dashboard UI**: `http://localhost:3000/iceberg` → Time Travel 카드 → 타임라인 시각화 + 시점 비교

### 5.2 Schema Evolution (스키마 변경)

```bash
# 현재 스키마 확인
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "DESCRIBE iceberg.netai.static_prims"}'

# 컬럼 추가
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims ADD COLUMN test_color VARCHAR"}'

# 컬럼 이름 변경
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims RENAME COLUMN test_color TO color"}'

# 컬럼 삭제
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims DROP COLUMN color"}'
```

> **Dashboard UI**: `http://localhost:3000/iceberg` → Schema Evolution 카드 → Add/Rename/Drop 탭

### 5.3 Compaction (파일 병합)

```bash
# 파일 현황 확인
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT file_path, file_format, record_count, file_size_in_bytes FROM iceberg.netai.\"static_prims$files\""}'

# 기본 Compaction 실행
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims EXECUTE optimize"}'

# 파일 크기 지정 Compaction
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims EXECUTE optimize(file_size_threshold => '\''128MB'\'')"}'
```

> **Dashboard UI**: Compaction 카드 → 파일 분석 → Optimize 실행 → 전/후 비교

### 5.4 Partition Evolution (파티셔닝 변경)

```bash
# 현재 DDL (파티셔닝 포함) 확인
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SHOW CREATE TABLE iceberg.netai.static_prims"}'

# 파티션 정보 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM iceberg.netai.\"static_prims$partitions\""}'
```

### 5.5 Metadata Explorer (메타데이터 탐색)

5개 메타데이터 테이블을 조회할 수 있습니다:

| 메타데이터 | SQL | 내용 |
|-----------|-----|------|
| Snapshots | `"table$snapshots"` | 스냅샷 ID, 시간, 작업 유형 |
| History | `"table$history"` | 스냅샷 이력 (현재/과거) |
| Files | `"table$files"` | 데이터 파일 경로, 크기, 행수 |
| Partitions | `"table$partitions"` | 파티션별 레코드/파일 수 |
| Manifests | `"table$manifests"` | 매니페스트 파일 목록 |

```bash
# 예: 매니페스트 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT path, length, added_snapshot_id, added_data_files_count FROM iceberg.netai.\"static_prims$manifests\""}'
```

> **Dashboard UI**: Metadata Explorer 카드 → 5개 탭 전환

### 5.6 Table Maintenance (테이블 유지보수)

```bash
# 오래된 스냅샷 만료 (7일 이상)
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "ALTER TABLE iceberg.netai.static_prims EXECUTE expire_snapshots(retention_threshold => '\''7d'\'')"}'
```

### 5.7 Hidden Partitioning / Sorting / COW vs MOR / ACID

이 기능들은 **Dashboard UI**에서 시각적 설명과 함께 제공됩니다:

- **Hidden Partitioning**: Transform 함수 6종 시각적 설명 + Digital Twin 추천
- **Sorting & Z-ordering**: 정렬 설정 + Z-order 개념 시각화
- **COW vs MOR**: 모드 비교 다이어그램 + 토글 전환
- **ACID Transactions**: 4가지 속성 설명 + OCC 동시성 제어 다이어그램

> **브라우저**: `http://localhost:3000/iceberg` → 각 기능 카드 클릭

---

## 6. Dashboard 페이지 검증

| 페이지 | URL | 기능 |
|--------|-----|------|
| Congestion | `/congestion` | 공간별 혼잡도 히트맵 |
| Static Prims | `/static` | 정적 Prim 데이터 조회 |
| Dynamic Objects | `/dynamic` | 동적 객체 실시간 모니터링 |
| SQL Query | `/query` | Trino SQL 직접 실행 |
| **Iceberg Features** | `/iceberg` | **10대 Iceberg 기능 허브** |

---

## 7. 자동 E2E 테스트 실행

```bash
cd Lakehouse
python test_e2e.py
```

### 테스트 항목 (27개)

| 카테고리 | 항목 수 | 내용 |
|---------|--------|------|
| Infrastructure Health | 5 | MinIO, Polaris, API, Dashboard 헬스체크 |
| Trino SQL Engine | 3 | SHOW SCHEMAS/TABLES, SELECT 1 |
| Lakehouse API | 3 | Deep health, Static spaces, Congestion |
| Iceberg Features SQL | 10 | DESCRIBE, DDL, $snapshots/$history/$files/$partitions/$manifests, Time Travel x2, COUNT |
| Dashboard Pages | 6 | /, /iceberg, /congestion, /static, /dynamic, /query |

### 기대 결과
```
TOTAL: 27/27 PASSED
```

---

## 8. 트러블슈팅

### .env 파일 누락
```bash
# 증상: docker compose up 시 환경변수 비어있음
cp example.env .env
docker compose up -d
```

### Polaris 권한 초기화
```bash
# 컨테이너 재생성 후 CATALOG_MANAGE_CONTENT 권한 리셋됨
# init-polaris-catalog.sh가 자동 재부여
docker compose restart polaris
```

### 메타데이터 테이블 쿼리 실패
```bash
# $snapshots 등은 테이블명만 따옴표로 감싸야 함
# 올바른 형식:
SELECT * FROM iceberg.netai."static_prims$snapshots"

# 잘못된 형식 (전체를 따옴표):
SELECT * FROM "iceberg.netai.static_prims$snapshots"  -- 에러!
```

### 헬스체크 IP
```bash
# Tailscale DNS 간섭 방지: 모든 healthcheck에 127.0.0.1 사용
# localhost 대신 127.0.0.1로 curl
```

### Time Travel 미래 시점 에러
```bash
# 증상: 미래 시점 쿼리 시 500 에러
# 원인: 해당 시점에 스냅샷이 없음
# 해결: $snapshots에서 실제 committed_at 시간 확인 후 사용
```

---

## 9. 데이터 흐름 다이어그램

```
Isaac Sim Extension (lakehouse.proto)
    │
    ├─ POST /api/v1/prims ────────────► Lakehouse API ──► Trino ──► Iceberg Table (static_prims)
    │                                                                    │
    ├─ POST /api/v1/dynamic/ingest ──► Lakehouse API ──► Trino ──► Iceberg Table (dynamic_*)
    │                                                                    │
    └─ POST /api/v1/upload-usd ──────► Lakehouse API ──► MinIO (usd-assets bucket)
                                                                         │
                                                                         ▼
Dashboard (:3000) ──► nginx proxy ──► Lakehouse API ──► Trino SQL ──► Iceberg/MinIO
    │
    ├─ /congestion ──► GET /api/v1/spaces/congestion/summary
    ├─ /static ─────► GET /api/v1/static/prims
    ├─ /dynamic ────► GET /api/v1/dynamic-objects/tables
    ├─ /query ──────► POST /api/v1/query (자유 SQL)
    └─ /iceberg ────► POST /api/v1/query (Iceberg 기능별 SQL 템플릿)
```

---

## 10. Iceberg Features Dashboard 스크린샷 가이드

1. **브라우저에서** `http://localhost:3000/iceberg` 접속
2. **허브 화면**: 10개 기능 카드 그리드 (아이콘 + 이름 + 설명)
3. **카드 클릭** → 상세 UI 진입
4. **테이블 선택** → 드롭다운에서 `iceberg.netai.static_prims` 선택
5. **기능 실행** → 버튼 클릭으로 SQL 자동 생성 & 실행
6. **결과 확인** → 테이블/차트/타임라인으로 시각화
7. **"이 기능이 뭔가요?"** → 접이식 설명 패널 (데모 시 교육용)
