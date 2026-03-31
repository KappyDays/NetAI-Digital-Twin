# Lakehouse Usage Guide — Q&A

> **원본 문서**: [LAKEHOUSE_USAGE_GUIDE.md](./LAKEHOUSE_USAGE_GUIDE.md)
> **작성일**: 2026-03-24

---

## Q1. FastAPI 미들웨어가 무엇인가?

### 짧은 답변

**Lakehouse API**(`localhost:8100`)를 가리킨다. Isaac Sim과 Lakehouse 내부 컴포넌트(Trino, Polaris, MinIO) 사이에서 **중간 다리(middleware)** 역할을 하는 FastAPI 기반 웹 서버이다.

### 상세 설명

**FastAPI**는 Python으로 REST API 서버를 빠르게 만들 수 있는 웹 프레임워크이다. 이 스택에서 FastAPI로 만든 서버를 "미들웨어"라고 부르는 이유는:

```
Isaac Sim Extension (클라이언트)
        │
        │  HTTP 요청 (예: POST /api/v1/prims)
        ▼
┌─────────────────────────────┐
│  FastAPI 미들웨어 (:8100)    │  ← 여기가 "미들웨어"
│  - 요청 검증/변환            │
│  - Trino SQL 실행 대행       │
│  - PyIceberg로 데이터 삽입   │
│  - MinIO에 파일 업로드       │
└─────────┬───────────────────┘
          │
    ┌─────┼─────┐
    ▼     ▼     ▼
  Trino  Polaris MinIO  (내부 컴포넌트)
```

클라이언트(Isaac Sim, 브라우저, curl)가 Trino/Polaris/MinIO에 직접 접근하는 대신, **FastAPI 서버가 중간에서 요청을 받아 적절한 내부 서비스로 라우팅**한다. 이것이 "미들웨어"로 불리는 이유이다.

**왜 직접 접근하지 않고 미들웨어를 두는가?**
- **단일 진입점**: 클라이언트는 `:8100` 하나만 알면 됨
- **추상화**: 내부 구조(Trino 쿼리 문법, Polaris 인증 등)를 감춤
- **비즈니스 로직**: 혼잡도 계산, 궤적 조회 등 복합 작업을 API 하나로 제공
- **인증/검증**: 요청 파라미터 검증, 에러 핸들링 등을 한 곳에서 처리

> **참고**: 엄밀히 말하면 FastAPI는 "웹 프레임워크"이고, 이 서버는 "API 서버" 또는 "백엔드 서버"가 더 정확한 표현이다. 문서에서 "미들웨어"라 부르는 것은 아키텍처 내에서의 역할(중간자)을 강조한 것이다.

---

## Q2. React SPA와 nginx가 무엇인가?

### 짧은 답변

- **React SPA**: 브라우저에서 실행되는 대시보드 웹 앱 (Single Page Application)
- **nginx**: 이 웹 앱 파일을 전달하고, API 요청을 중계하는 웹 서버

### 상세 설명

#### React SPA

**React**는 Facebook이 만든 UI 라이브러리로, 웹 페이지를 컴포넌트 단위로 구축한다. **SPA(Single Page Application)**는 페이지 전환 없이 하나의 HTML 파일 안에서 JavaScript가 화면을 동적으로 바꾸는 방식이다.

이 스택의 Dashboard(`localhost:3000`)가 React SPA이다:
- Congestion 히트맵 페이지
- Static/Dynamic Objects 페이지
- SQL Query 페이지

이 모든 페이지가 하나의 앱 안에서 전환되며, 페이지를 이동할 때 서버에서 새 HTML을 받지 않는다.

#### nginx

**nginx**는 웹 서버/리버스 프록시이다. Dashboard 컨테이너 안에서 두 가지 역할을 한다:

```
브라우저 (localhost:3000)
    │
    ▼
┌─────────── nginx ───────────┐
│                              │
│  /              → React 앱 파일 전달 (HTML, JS, CSS)
│  /api/*         → Lakehouse API (:8100)로 프록시
│                              │
└──────────────────────────────┘
```

1. **정적 파일 서빙**: 빌드된 React 앱 파일(HTML, JS, CSS)을 브라우저에 전달
2. **리버스 프록시**: 브라우저에서 `/api/*` 요청이 오면 Lakehouse API(:8100)로 전달 → CORS 문제 없이 API 호출 가능

즉, 사용자가 `localhost:3000`에 접속하면 nginx가 React 앱을 전달하고, 앱 내에서 API를 호출하면 nginx가 그 요청을 백엔드로 중계하는 구조이다.

---

## Q3. Lakehouse 구조에서 메타데이터를 관리하는 것은 Polaris, Iceberg, Trino 중 무엇인가?

### 짧은 답변

**Polaris**와 **Iceberg**가 함께 관리한다. Trino는 메타데이터를 관리하지 않는다.

### 상세 설명

"메타데이터 관리"는 여러 계층에 걸쳐 있다. 역할을 명확히 구분하면:

| 컴포넌트 | 메타데이터 역할 | 비유 |
|---------|---------------|------|
| **Iceberg** (테이블 포맷) | 메타데이터의 **정의자** — 스냅샷, 스키마, 파티션, 매니페스트 등의 메타데이터 구조를 정의하고 생성 | 메타데이터의 "규격서" |
| **Polaris** (REST 카탈로그) | 메타데이터의 **저장/조회 서비스** — Iceberg가 생성한 메타데이터를 저장하고, "이 테이블의 최신 메타데이터는 어디에 있는가?"를 응답 | 메타데이터의 "도서관 사서" |
| **Trino** (쿼리 엔진) | 메타데이터의 **소비자** — Polaris에게 메타데이터 위치를 물어보고, 그 정보로 데이터를 읽어 SQL 결과를 반환 | 메타데이터의 "독자" |

```
Iceberg 메타데이터 파일 (metadata.json, manifest 등)
    │
    │  저장 위치를 가리키는 포인터
    ▼
Polaris 카탈로그 (REST API)
    │
    │  "이 테이블의 메타데이터는 s3://warehouse2/netai/... 에 있어"
    ▼
Trino (쿼리 시 Polaris에 질의)
```

핵심: Iceberg가 메타데이터를 **만들고**, Polaris가 그 위치를 **추적/제공**하며, Trino는 그걸 **읽어서 사용**한다.

---

## Q4. Polaris는 메타데이터 포인터를 저장하는 Catalog로만 알고 있는데, Polaris가 메타데이터를 직접 관리하는 건가?

### 짧은 답변

맞다. Polaris는 **메타데이터를 "직접" 관리하는 것이 아니라, 메타데이터의 "위치(포인터)"를 관리**한다. 문서의 "테이블 메타데이터 관리"라는 표현은 약간 오해의 여지가 있다.

### 상세 설명

질문자의 이해가 정확하다. 좀 더 엄밀하게 정리하면:

#### Polaris가 실제로 하는 일

```
Polaris 내부 저장 정보:
┌─────────────────────────────────────┐
│ Catalog: iceberg2                    │
│   ├── Namespace: netai           │
│   │     └── Table: static_prims      │
│   │           └── metadata-location: │
│   │              "s3://warehouse2/netai/static_prims/metadata/v3.metadata.json"
│   └── Namespace: dynamic_db          │
│         └── Table: dynamic_worker_01 │
│               └── metadata-location: │
│                  "s3://warehouse2/dynamic_db/dynamic_worker_01/metadata/v1.metadata.json"
└─────────────────────────────────────┘
```

- Polaris는 **"static_prims 테이블의 최신 메타데이터 파일은 S3의 이 경로에 있다"**라는 포인터를 저장
- 실제 메타데이터 파일(스키마 정보, 스냅샷 목록, 매니페스트 경로 등)은 **MinIO(S3)에 저장**된 Iceberg 포맷 파일
- Polaris는 추가로 **네임스페이스 관리, OAuth2 인증, 접근 권한 제어** 등의 카탈로그 관리 기능을 수행

#### 문서 표현의 의도

문서에서 "테이블 메타데이터 관리"라고 쓴 것은, Polaris가 **카탈로그로서 테이블의 메타데이터 접근을 관리(중재)한다**는 의미이다. 메타데이터 파일 자체를 저장하거나 생성하는 것이 아니다.

더 정확한 표현: **"테이블 메타데이터 위치 관리 + 카탈로그 서비스"**

---

## Q5. Polaris에서 관리하는 카탈로그 단위인 Warehouse:iceberg2는 데이터베이스 이름과 동일한 역할인가?

### 짧은 답변

아니다. **Warehouse(iceberg2)는 데이터베이스보다 상위 개념**으로, 관계형 DB에서의 "서버 인스턴스" 또는 "카탈로그"에 가깝다.

### 상세 설명

Lakehouse 스택의 계층 구조와 관계형 DB의 계층을 대응시키면:

| Lakehouse (Polaris/Iceberg) | 관계형 DB (MySQL 등) | 이 스택에서의 값 |
|----------------------------|---------------------|----------------|
| **Warehouse (Catalog)** | Server Instance / Catalog | `iceberg2` |
| **Namespace** | Database (Schema) | `netai`, `dynamic_db` |
| **Table** | Table | `static_prims`, `dynamic_worker_01` |

```
iceberg2 (Warehouse = Catalog)
    ├── netai (Namespace ≈ Database)
    │     └── static_prims (Table)
    └── dynamic_db (Namespace ≈ Database)
          ├── dynamic_worker_01 (Table)
          ├── dynamic_worker_02 (Table)
          └── dynamic_robot_01 (Table)
```

즉, **`iceberg2`는 데이터베이스가 아니라 그 위의 카탈로그**이고, **데이터베이스에 해당하는 것은 `netai`와 `dynamic_db`(Namespace)**이다.

Trino에서 SQL을 쓸 때도 이 계층이 드러난다:
```sql
SELECT * FROM iceberg.netai.static_prims
--           ───────  ─────────  ────────────
--           Catalog  Namespace  Table
--           (=Warehouse) (=DB)
```

> **주의**: Trino에서 `iceberg`라고 쓰는 것은 Trino 커넥터 이름이다. Polaris의 Warehouse 이름 `iceberg2`와는 다르다. Trino 설정에서 `iceberg` 커넥터가 Polaris의 `iceberg2` Warehouse를 가리키도록 연결되어 있다.

---

## Q6. Namespace: netai와 dynamic_db는 iceberg2 데이터베이스에 존재하는 table의 이름인가?

### 짧은 답변

아니다. **Namespace는 테이블이 아니라, 테이블들을 그룹화하는 "데이터베이스(스키마)"**이다.

### 상세 설명

Q5에서 정리한 계층 구조를 다시 보면:

```
iceberg2 (Warehouse/Catalog) — "데이터베이스"가 아님
    │
    ├── netai (Namespace) — "테이블"이 아니라 테이블을 담는 "그룹(=DB)"
    │     └── static_prims    — 이것이 실제 테이블
    │
    └── dynamic_db (Namespace) — 마찬가지로 테이블 그룹
          ├── dynamic_worker_01  — 실제 테이블
          ├── dynamic_worker_02  — 실제 테이블
          └── dynamic_robot_01   — 실제 테이블
```

- `netai` = 정적 Prim 데이터를 담는 **네임스페이스(≈ 데이터베이스)**
- `dynamic_db` = 동적 IoT/센서 데이터를 담는 **네임스페이스(≈ 데이터베이스)**
- 이 안에 들어 있는 `static_prims`, `dynamic_worker_01` 등이 **실제 테이블**

Trino 명령으로 확인하면:
```sql
SHOW SCHEMAS FROM iceberg;
-- 결과: netai, dynamic_db  ← 이것이 Namespace(≈ DB)

SHOW TABLES FROM iceberg.netai;
-- 결과: static_prims            ← 이것이 테이블

SHOW TABLES FROM iceberg.dynamic_db;
-- 결과: dynamic_worker_01, dynamic_robot_01, ...  ← 이것들이 테이블
```

---

## Q7. Swagger UI라고 부르는 REST API middleware가 정확히 뭔지 설명해줘.

### 짧은 답변

**Swagger UI는 미들웨어가 아니라**, FastAPI가 자동 생성하는 **API 문서 + 테스트 웹 페이지**이다.

### 상세 설명

#### Swagger UI란?

Swagger UI는 REST API의 **인터랙티브 문서화 도구**이다. API의 모든 엔드포인트, 파라미터, 요청/응답 스키마를 웹 페이지로 보여주고, "Try it out" 버튼으로 실제 API 호출까지 할 수 있다.

```
http://localhost:8100/docs   ← 이 URL이 Swagger UI
```

#### FastAPI와의 관계

FastAPI는 코드에서 API를 정의하면 **자동으로** Swagger UI를 생성한다:

```python
# FastAPI 코드에 이런 엔드포인트가 있으면
@app.post("/api/v1/prims")
async def insert_prims(records: List[PrimRecord]):
    ...

# → http://localhost:8100/docs 에 자동으로 문서가 생김
#   - POST /api/v1/prims 엔드포인트 설명
#   - PrimRecord 스키마 표시
#   - "Try it out" 테스트 버튼
```

#### 구조 정리

```
┌─────────────────────── FastAPI 서버 (:8100) ───────────────────────┐
│                                                                     │
│  /docs          → Swagger UI (API 문서 웹 페이지) ← 자동 생성       │
│  /api/v1/prims  → 실제 API 엔드포인트                                │
│  /api/v1/query  → 실제 API 엔드포인트                                │
│  /health        → 실제 API 엔드포인트                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Swagger UI ≠ 미들웨어**. Swagger UI는 FastAPI 미들웨어(Lakehouse API 서버)에 **내장된 문서 페이지**이다. 별도의 서비스나 컴포넌트가 아니라, FastAPI 서버의 `/docs` 경로에서 자동으로 제공되는 기능이다.

#### 실제 사용 시

1. 브라우저에서 `http://localhost:8100/docs` 접속
2. 전체 API 목록이 카테고리별로 표시됨
3. 특정 API 클릭 → "Try it out" → 파라미터 입력 → "Execute" → 결과 확인
4. curl 명령어도 자동 생성되어 복사 가능

---

## Q8. MinIO에 저장된 warehouse2/netai에서 warehouse2가 bucket 이름이자 Lakehouse의 Catalog 이름일까? 아니면 Lakehouse의 db 이름일까?

### 짧은 답변

**warehouse2는 MinIO의 bucket 이름**이다. Catalog 이름(`iceberg2`)과도 다르고, DB(Namespace) 이름(`netai`)과도 다르다. 이름이 비슷해서 혼동하기 쉽지만 별개의 개념이다.

### 상세 설명

이 스택에서 이름이 비슷한 세 가지를 명확히 구분하면:

| 이름 | 정체 | 위치 | 역할 |
|------|------|------|------|
| `warehouse2` | **MinIO Bucket** | MinIO (S3 스토리지) | 실제 데이터 파일(Parquet, metadata JSON)이 저장되는 물리적 컨테이너 |
| `iceberg2` | **Polaris Warehouse (Catalog)** | Polaris (카탈로그 서비스) | 테이블 메타데이터 위치를 추적하는 논리적 카탈로그 |
| `netai` / `dynamic_db` | **Namespace (≈ Database)** | Polaris 내부 (iceberg2 하위) | 테이블을 그룹화하는 논리적 단위 |

이들의 관계:

```
Polaris (카탈로그 서비스)
    └── iceberg2 (Warehouse/Catalog)
            ├── netai (Namespace)
            │     └── static_prims (Table)
            │           metadata-location: "s3://warehouse2/netai/static_prims/metadata/..."
            └── dynamic_db (Namespace)                    ──────────
                                                          이 부분이 MinIO bucket 이름

MinIO (스토리지)
    └── warehouse2 (Bucket) ← 물리적 저장소
            ├── netai/
            │     └── static_prims/
            │           ├── metadata/    ← Iceberg 메타데이터 파일
            │           └── data/        ← Parquet 데이터 파일
            ├── dynamic_db/
            │     └── dynamic_worker_01/
            └── usd/
                  └── world_prims/       ← USD 파일
```

#### 왜 이름이 다른가?

- `warehouse2` (bucket)과 `iceberg2` (catalog)의 이름이 다른 이유: **물리적 저장소(bucket)와 논리적 카탈로그(catalog)는 독립적인 개념**이기 때문
- Polaris 설정에서 `iceberg2` 카탈로그가 `s3://warehouse2/` 를 기본 저장 경로로 사용하도록 연결되어 있음
- 이 연결은 `polaris-init` 컨테이너가 초기화 시 설정

#### 환경변수와의 대응

```
ICEBERG_WAREHOUSE = iceberg2    → Polaris Catalog 이름
S3_BUCKET         = warehouse2  → MinIO Bucket 이름
ICEBERG_NAMESPACE = netai   → Polaris Namespace (≈ DB)
```

---

## Q9. Iceberg를 활용하는 내용은 이 문서의 범위가 아닐까? schema evolution이나 partitioning이나 metadata, snapshot 등을 관리하고 활용하는 방법이 있는 걸로 알고 있는데.

### 짧은 답변

맞다. 이 문서는 **Lakehouse 스택의 "사용 방법(How to access)"**에 초점을 맞추고 있으며, **Iceberg 자체의 고급 기능 활용법은 범위 밖**이다.

### 상세 설명

#### 이 문서가 다루는 범위

```
[이 문서의 범위]
├── 아키텍처 개요 (어떤 컴포넌트가 어떻게 연결되는가)
├── 접근 방법 (CLI, Web UI, API, Extension으로 어떻게 접속하는가)
├── 기본 워크플로우 (데이터 삽입, 조회, USD 업로드)
└── 트러블슈팅
```

#### 이 문서가 다루지 않는 Iceberg 기능

| Iceberg 기능 | 설명 | Trino SQL 예시 |
|-------------|------|---------------|
| **Schema Evolution** | 테이블 스키마를 무중단으로 변경 (컬럼 추가/삭제/이름변경/타입변경). 기존 데이터에 영향 없음 | `ALTER TABLE iceberg.netai.static_prims ADD COLUMN color VARCHAR` |
| **Partition Evolution** | 기존 데이터 재작성 없이 파티션 전략 변경 | `ALTER TABLE ... SET PROPERTIES partitioning = ARRAY['month(timestamp)']` |
| **Snapshot Management** | 테이블의 모든 변경 이력을 스냅샷으로 보존. 특정 시점으로 롤백 가능 | `SELECT * FROM iceberg.netai.static_prims FOR TIMESTAMP AS OF TIMESTAMP '2026-03-23 12:00:00'` |
| **Time Travel** | 과거 특정 시점의 데이터를 조회 | `SELECT * FROM "static_prims$snapshots"` |
| **Metadata Tables** | 스냅샷, 매니페스트, 히스토리 등 메타데이터를 SQL로 조회 | `SELECT * FROM "static_prims$history"` |
| **Compaction** | 작은 파일들을 큰 파일로 병합하여 쿼리 성능 향상 | `ALTER TABLE ... EXECUTE optimize` |
| **Expire Snapshots** | 오래된 스냅샷을 정리하여 스토리지 절약 | `ALTER TABLE ... EXECUTE expire_snapshots(retention_threshold => '7d')` |
| **Hidden Partitioning** | 사용자가 파티션을 의식하지 않아도 쿼리 최적화가 자동으로 적용 | 파티셔닝 설정 후 일반 WHERE 절 사용 |

#### 보완 문서 제안

Iceberg 활용 가이드를 별도로 작성한다면 다음 구조를 권장:

```
ICEBERG_FEATURES_GUIDE.md
├── 1. Schema Evolution (스키마 변경)
├── 2. Partitioning (파티셔닝 전략)
├── 3. Snapshot & Time Travel (시점 조회/롤백)
├── 4. Metadata Tables (메타데이터 SQL 조회)
├── 5. Compaction & Maintenance (파일 최적화)
└── 6. 이 Lakehouse 스택에서의 실전 적용
```

#### 참고 문서

- [Apache Iceberg 공식 문서](https://iceberg.apache.org/docs/latest/)
- [Trino Iceberg Connector](https://trino.io/docs/current/connector/iceberg.html)
- [Iceberg Table Spec](https://iceberg.apache.org/spec/)

---

## 보충 분석: 질문 패턴에서 파악한 혼동 지점

질문들을 분석하면 크게 **세 가지 혼동 패턴**이 보인다.

---

### 혼동 1: Lakehouse 스택 계층 구조의 용어 혼동

**관련 질문**: Q3, Q4, Q5, Q6, Q8

질문의 핵심은 **"누가 무엇을 하는가"**와 **"이 이름이 어느 계층에 속하는가"**를 구분하는 것이다. 이 스택에서는 비슷한 역할을 하는 듯한 컴포넌트가 여러 개 있고, 이름도 혼동을 유발한다.

#### 전체 계층 맵

```
물리 계층 (어디에 저장되나?)
──────────────────────────────
MinIO
  └── warehouse2 (Bucket) ← 실제 파일이 여기에 저장
        ├── netai/static_prims/data/*.parquet     ← 데이터
        ├── netai/static_prims/metadata/*.json    ← 메타데이터
        └── usd/world_prims/*.usda                    ← USD 파일

논리 계층 (어떻게 조직되나?)
──────────────────────────────
Polaris (카탈로그 서비스)
  └── iceberg2 (Warehouse = Catalog)
        ├── netai (Namespace ≈ Database)
        │     └── static_prims (Table)
        └── dynamic_db (Namespace ≈ Database)
              └── dynamic_worker_01 (Table)

접근 계층 (어떻게 사용하나?)
──────────────────────────────
Trino (SQL 엔진)
  └── iceberg (Connector 이름, Polaris의 iceberg2에 연결)
        ├── netai (Schema = Namespace)
        └── dynamic_db (Schema = Namespace)
```

#### 이름 대응표

| 이름 | 계층 | 개념 | RDBMS 비유 |
|------|------|------|-----------|
| `warehouse2` | 물리 | S3 Bucket | 디스크 볼륨 |
| `iceberg2` | 논리 | Polaris Catalog (Warehouse) | 서버 인스턴스 |
| `iceberg` | 접근 | Trino Connector 이름 | JDBC 연결 이름 |
| `netai` | 논리 | Namespace | 데이터베이스(스키마) |
| `static_prims` | 논리 | Table | 테이블 |

**핵심**: `warehouse2`(물리) ≠ `iceberg2`(논리 카탈로그) ≠ `iceberg`(Trino 커넥터). 셋은 서로 다른 계층에 있는 별개의 이름이다.

---

### 혼동 2: 컴포넌트의 역할 경계

**관련 질문**: Q1, Q2, Q7

문서에서 사용하는 용어가 기술적으로 완전히 정확하지 않아 발생하는 혼동이다:

| 문서 표현 | 실제 의미 | 정확한 표현 |
|-----------|----------|------------|
| "FastAPI 미들웨어" | FastAPI 기반 API 서버 | "API 서버" 또는 "백엔드 서버" |
| "React SPA + nginx" | React 앱을 nginx가 서빙 | "웹 대시보드 (React 프론트엔드 + nginx 웹 서버)" |
| "Swagger UI (REST API middleware)" | FastAPI에 내장된 API 문서 페이지 | "Swagger UI (API 문서/테스트 인터페이스)" |
| "테이블 메타데이터 관리" (Polaris) | 메타데이터 위치 포인터 관리 | "메타데이터 위치 추적 + 카탈로그 서비스" |

**제안**: 문서를 업데이트할 때 이러한 표현을 좀 더 정확하게 수정하면, 처음 읽는 사람의 혼동을 줄일 수 있다.

---

### 혼동 3: 문서 범위와 Iceberg 기능의 경계

**관련 질문**: Q9

이 문서가 "Lakehouse **사용** 가이드"인 만큼, Iceberg의 고급 기능(schema evolution, time travel 등)은 의도적으로 빠져 있다. 하지만 문서 제목만 보면 Iceberg 활용법도 포함될 것으로 기대할 수 있다.

**제안**:
- 문서 서두에 "이 문서의 범위: 스택 접근 방법 및 기본 워크플로우. Iceberg 고급 기능은 별도 문서 참조" 명시
- 또는 Iceberg 기능 가이드를 별도로 작성하여 링크

---

*작성일: 2026-03-24*
