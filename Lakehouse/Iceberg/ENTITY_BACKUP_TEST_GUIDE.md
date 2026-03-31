# Entity-Level 3-Level Backup System 테스트 가이드

## 개요

Entity-Level 3-Level 백업/변경감지/복원 시스템의 E2E 테스트 가이드.

- **L1 Entity Table**: entity_hash 기반 빠른 변경 감지
- **L2 Prim Snapshot Table**: sub-prim hash + JSON properties 상세 비교
- **L3 USD Binary**: MinIO에 Entity 서브트리 .usd 파일 저장/복원

---

## 사전 조건

```bash
cd Lakehouse/Iceberg
cp example.env .env        # 처음인 경우
./start.sh                 # 또는 docker compose up -d --build
```

5개 서비스가 모두 healthy 상태여야 합니다:
- MinIO (:9000, :9001)
- Polaris (:8181)
- Trino (:8900)
- Lakehouse API (:8100)
- Dashboard (:3000)

---

## Phase 1: 인프라 확인 (자동 실행 완료)

### 1-1. Docker 서비스 상태

```bash
docker compose ps
```

| 서비스 | 상태 | 포트 |
|--------|------|------|
| minio | Up (healthy) | 9000-9001 |
| polaris | Up (healthy) | 8181-8182 |
| trino | Up (healthy) | 8900 |
| lakehouse-api | Up (healthy) | 8100 |
| dashboard | Up (healthy) | 3000 |

**결과: PASS** - 5개 서비스 모두 healthy

### 1-2. API Health Check

```bash
curl http://localhost:8100/api/v1/health
```

**결과: PASS** - `{"status": "ok", "version": "1.0.0"}`

### 1-3. Iceberg 테이블 확인

```bash
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SHOW TABLES FROM iceberg.netai"}'
```

**결과: PASS** - 5개 테이블 확인
- `entities` (Entity 메타데이터)
- `prim_snapshots` (Sub-Prim 스냅샷)
- `static_prims` (기존 Static Prim)
- `dynamic_world_robots_jetbot` (샘플 IoT)
- `dynamic_world_robots_kaya` (샘플 IoT)

---

## Phase 2: API 엔드포인트 테스트 (자동 실행 완료)

### 2-1. POST /api/v1/entities/backup

Entity + Prim Snapshot 데이터를 Iceberg에 배치 INSERT.

```bash
curl -X POST http://localhost:8100/api/v1/entities/backup \
  -H "Content-Type: application/json" \
  -d '{
    "backup_time": "2026-03-26 10:00:00.000",
    "entities": [{
      "entity_id": "test-001",
      "entity_path": "/World/Robots/Jetbot",
      "entity_type": "Xform",
      "source_type": "reference",
      "source_asset": "/Isaac/Robots/Jetbot/jetbot.usd",
      "is_dynamic": true,
      "dynamic_table": "dynamic_robots_jetbot",
      "child_count": 3,
      "entity_hash": "a3f8c2e1b7d94f02",
      "usd_file_path": "s3://warehouse2/usd/jetbot_20260326.usd"
    }],
    "prim_snapshots": [{
      "entity_path": "/World/Robots/Jetbot",
      "relative_path": "/Lidar",
      "prim_type": "Xform",
      "properties": "{\"intensity\": 1.0, \"range\": 10.0}",
      "prim_hash": "1111111111111111"
    }]
  }'
```

**결과: PASS** - `entities_inserted: 2, prims_inserted: 2`

### 2-2. GET /api/v1/entities/backup-times

```bash
curl http://localhost:8100/api/v1/entities/backup-times
```

**결과: PASS** - 3개 백업 시점 반환: `12:00, 11:00, 10:00`

### 2-3. GET /api/v1/entities/list

```bash
curl "http://localhost:8100/api/v1/entities/list?backup_time=2026-03-26+10:00:00.000"
```

**결과: PASS** - 2개 Entity 반환 (Environment/Grid, Robots/Jetbot)

### 2-4. GET /api/v1/entities/diff

두 시점의 Entity 해시를 비교하여 변경/추가/삭제 감지.

```bash
curl "http://localhost:8100/api/v1/entities/diff?time_a=2026-03-26+10:00:00.000&time_b=2026-03-26+11:00:00.000"
```

**결과: PASS**
- `added: 1` (/World/Props/Block_A - 11시에 새로 추가됨)
- `changed: 1` (/World/Robots/Jetbot - 해시 변경됨)
- `unchanged: 1` (/World/Environment/Grid - 동일)

### 2-5. GET /api/v1/entities/{path}/prim-diff

특정 Entity 내 Sub-Prim별 해시 비교 + before/after properties.

```bash
curl "http://localhost:8100/api/v1/entities/World/Robots/Jetbot/prim-diff?time_a=2026-03-26+10:00:00.000&time_b=2026-03-26+11:00:00.000"
```

**결과: PASS**
- `/Camera`: unchanged (hash 동일)
- `/Lidar`: **changed** — `intensity: 1.0→2.0, range: 10.0→15.0`

### 2-6. GET /api/v1/entities/{path}/restore

복원에 필요한 Entity 정보 + 모든 Sub-Prim 스냅샷 반환.

```bash
curl "http://localhost:8100/api/v1/entities/World/Robots/Jetbot/restore?backup_time=2026-03-26+10:00:00.000"
```

**결과: PASS** - entity 정보 + 2개 prim_snapshots (Camera, Lidar) 반환

### 2-7. POST /api/v1/dynamic/sample-ingest

Dynamic Entity에 대한 가짜 IoT 데이터 생성.

```bash
curl -X POST http://localhost:8100/api/v1/dynamic/sample-ingest \
  -H "Content-Type: application/json" \
  -d '{"entity_path": "/World/Robots/Jetbot", "count": 5}'
```

**결과: PASS** - `records_generated: 5, table_name: dynamic_world_robots_jetbot`

---

## Phase 3: 보안 테스트 (자동 실행 완료)

### 3-1. SQL Injection 차단

```bash
curl "http://localhost:8100/api/v1/entities/list?backup_time=';DROP+TABLE+entities--"
```

**결과: PASS** - `{"detail": "Invalid timestamp format"}` (400 Bad Request)

### 3-2. Invalid Table Name 차단

```bash
curl -X POST http://localhost:8100/api/v1/dynamic/sample-ingest \
  -H "Content-Type: application/json" \
  -d '{"entity_path": "; DROP TABLE--", "count": 1}'
```

**결과: PASS** - `{"detail": "Invalid identifier for table name"}` (400 Bad Request)

---

## Phase 4: Dashboard 테스트 (자동 실행 완료)

### 4-1. Dashboard 접근

```
http://localhost:3000
```

**결과: PASS** - HTTP 200

### 4-2. Entity Diff 페이지 (수동 확인 필요)

브라우저에서 다음 절차를 수행합니다:

1. `http://localhost:3000/entity-diff` 접속
2. **"Load Backup Times"** 버튼 클릭
3. **Time A** 드롭다운에서 `2026-03-26T10:00:00` 선택
4. **Time B** 드롭다운에서 `2026-03-26T11:00:00` 선택
5. **"Compare"** 버튼 클릭

**확인 사항:**
- [ ] Entity 목록이 3개 표시되는지 (Grid=unchanged, Block_A=added, Jetbot=changed)
- [ ] 색상 구분: 초록(unchanged), 초록(added), 주황(changed)
- [ ] **Jetbot** 행 클릭 → Sub-Prim 비교 뷰로 전환
- [ ] Camera=unchanged, Lidar=changed 표시
- [ ] **Lidar** 행 클릭 → JSON before/after 비교 뷰
- [ ] Before: `intensity: 1.0, range: 10.0` / After: `intensity: 2.0, range: 15.0`
- [ ] 변경된 값이 주황색으로 하이라이팅
- [ ] "Back" 버튼으로 상위 레벨 복귀

---

## Phase 5: Isaac Sim Extension 테스트 (수동 — Isaac Sim 필요)

Isaac Sim 5.1.0이 설치된 환경에서 수행합니다.

### 사전 설정

1. Isaac Sim 실행
2. Extension Manager (Window > Extensions)에서 `KKR.Lakehouse` 검색 후 활성화
3. Tools > KKR-Tools > KKR.Lakehouse 클릭하여 Extension 패널 열기
4. **API Base URL**을 `http://localhost:8100`으로 설정 (Docker 외부에서 접근 시)
5. **"PING API"** 버튼으로 연결 확인

### 5-1. Stage Setup

1. **"SETUP STAGE"** 버튼 클릭
2. Stage Hierarchy에서 확인:

```
/World
├── /Environment
│   ├── /Grid        (Reference → default_environment.usd)
│   └── /Table       (Reference → table_instanceable.usd)
├── /Robots
│   ├── /Jetbot      (Reference → jetbot.usd)
│   └── /Kaya        (Reference → kaya.usd)
└── /Props
    ├── /Block_A     (Reference → basic_block.usd)
    └── /Block_B     (Reference → basic_block.usd)
```

**확인 사항:**
- [ ] /World 아래 3개 Xform (Environment, Robots, Props) 생성됨
- [ ] 각 Xform에 2개 이상의 Reference Prim 존재
- [ ] Viewport에서 에셋이 시각적으로 확인됨
- [ ] Nucleus 연결 필요 (연결 안 된 경우 에러 메시지 표시)

### 5-2. Entity Backup

1. **"BACKUP"** 버튼 클릭
2. Status 라벨에서 결과 확인

**확인 사항:**
- [ ] "Status: Done" 표시
- [ ] Entity 수 (6개 이상: Grid, Table, Jetbot, Kaya, Block_A, Block_B)
- [ ] Prim 수 표시
- [ ] Status/Log에 API response 출력
- [ ] `http://localhost:8100/api/v1/entities/backup-times`에 새 시점 추가됨
- [ ] MinIO Console (`http://localhost:9001`)에서 USD 파일 업로드 확인

### 5-3. Prim 수정 후 재백업

1. Viewport에서 Jetbot 선택 → Property 패널에서 Transform 변경 (예: Position X를 2.0으로)
2. **"BACKUP"** 버튼 다시 클릭
3. Dashboard에서 두 시점 비교

**확인 사항:**
- [ ] 재백업 성공
- [ ] Dashboard Entity Diff에서 Jetbot이 "changed"로 표시
- [ ] Jetbot Sub-Prim drill-down에서 변경된 속성 확인 가능

### 5-4. Entity Restore

1. **"LOAD TIMES"** 버튼 클릭 → 백업 시점 로드
2. `<` `>` 버튼으로 이전 백업 시점 선택
3. **"LOAD ENTITIES"** 버튼 클릭 → Entity 목록 로드
4. 복원할 Entity 선택 (예: Jetbot)
5. **"RESTORE"** 버튼 클릭

**확인 사항:**
- [ ] 기존 Entity가 Stage에서 제거되고 이전 버전으로 복원됨
- [ ] Reference 에셋의 경우 원본 Nucleus 에셋으로 Reference 재설정
- [ ] Status/Log에 복원 방법 (Level 2/3) 표시

### 5-5. Stage Clear

1. **"CLEAR STAGE"** 버튼 클릭

**확인 사항:**
- [ ] /World 하위 모든 Prim 제거됨
- [ ] Stage Hierarchy에 /World만 남음

### 5-6. Sample IoT 데이터 생성

1. Entity Path에 `/World/Robots/Jetbot` 입력
2. Record Count에 `10` 입력
3. **"GENERATE IOT"** 버튼 클릭

**확인 사항:**
- [ ] 성공 메시지 + table_name 표시
- [ ] `http://localhost:8100/api/v1/query`에서 확인:
  ```sql
  SELECT * FROM iceberg.netai.dynamic_world_robots_jetbot ORDER BY timestamp DESC LIMIT 5
  ```

---

## Phase 6: Iceberg 데이터 검증 (자동 실행 완료)

### 6-1. 테이블 데이터 현황

| 테이블 | 레코드 수 | 비고 |
|--------|-----------|------|
| entities | 7 | 3개 백업 시점 x 2~3 entities |
| prim_snapshots | 5 | Jetbot Sub-Prims (Camera, Lidar) |
| dynamic_world_robots_jetbot | 10 | 샘플 IoT 데이터 |
| dynamic_world_robots_kaya | 3 | 샘플 IoT 데이터 |
| static_prims | 기존 데이터 | 이전 테스트 데이터 |

### 6-2. Trino SQL 직접 확인

```bash
# Entity 전체 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT entity_path, entity_hash, backup_time FROM iceberg.netai.entities ORDER BY backup_time, entity_path"}'

# Prim Snapshot 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT entity_path, relative_path, prim_hash FROM iceberg.netai.prim_snapshots ORDER BY entity_path, relative_path"}'

# Dynamic IoT 최신 데이터
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM iceberg.netai.dynamic_world_robots_jetbot ORDER BY timestamp DESC LIMIT 5"}'
```

---

## 테스트 요약

| Phase | 항목 | 방법 | 결과 |
|-------|------|------|------|
| 1 | Docker 서비스 | 자동 | PASS (5/5 healthy) |
| 2 | API 7개 엔드포인트 | 자동 | PASS (7/7) |
| 3 | 보안 (SQL injection) | 자동 | PASS |
| 4-1 | Dashboard 접근 | 자동 | PASS (HTTP 200) |
| 4-2 | Dashboard Entity Diff UI | **수동** | 브라우저에서 확인 필요 |
| 5 | Isaac Sim Extension | **수동** | Isaac Sim 환경 필요 |
| 6 | Iceberg 데이터 검증 | 자동 | PASS |

**자동 테스트 결과: 9/9 PASS**
**수동 테스트: 2개 Phase 남음 (Dashboard UI 확인 + Isaac Sim Extension)**
