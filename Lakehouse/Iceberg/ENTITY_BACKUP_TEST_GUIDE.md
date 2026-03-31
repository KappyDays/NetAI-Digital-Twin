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
  -d '{"sql": "SHOW TABLES FROM polaris.netai"}'
```

**결과: PASS** - 3개 테이블 확인
- `entities` (Entity 메타데이터)
- `prim_snapshots` (Sub-Prim 스냅샷)
- `raw_backup_files` (Raw Backup 파일 메타데이터)

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


---

## Phase 3: 보안 테스트 (자동 실행 완료)

### 3-1. SQL Injection 차단

```bash
curl "http://localhost:8100/api/v1/entities/list?backup_time=';DROP+TABLE+entities--"
```

**결과: PASS** - `{"detail": "Invalid timestamp format"}` (400 Bad Request)

### 3-2. Invalid Table Name 차단

```bash
curl -X POST http://localhost:8100/api/v1/entities/backup \
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

## Phase 5: Nucleus Pipeline 및 Isaac Sim Extension 테스트 (수동)

Nucleus 서버 및 Isaac Sim 5.1.0이 설치된 환경에서 수행합니다.

> **참고**: Task 1/2는 `nucleus_pipeline/` CLI로 수행합니다. Omniverse Extension은 Task 3 복원(`KKR.TimeTravel`)에만 사용됩니다.

### 5-1. nucleus_pipeline — Task 1 (Raw Backup)

Nucleus 서버의 폴더를 MinIO에 증분 백업하고 Iceberg에 메타데이터를 기록합니다.

```bash
cd nucleus_pipeline
python main.py --raw-backup --nucleus-folder omniverse://10.38.38.48/Projects/MyProject
```

**확인 사항:**
- [ ] 실행 성공 (오류 없이 완료)
- [ ] `http://localhost:8100/api/v1/raw-backup/times`에 백업 시점 추가됨
- [ ] MinIO Console (`http://localhost:9001`)에서 파일 업로드 확인

### 5-2. nucleus_pipeline — Task 2 (Entity Backup)

Nucleus USD 파일의 root layer overrides를 파싱하여 Entity/Prim 스냅샷을 Iceberg에 저장합니다.

```bash
cd nucleus_pipeline
python main.py --nucleus-path omniverse://10.38.38.48/Projects/MyProject/World.usd
```

**확인 사항:**
- [ ] 실행 성공 (오류 없이 완료)
- [ ] `http://localhost:8100/api/v1/entities/backup-times`에 새 시점 추가됨
- [ ] MinIO Console (`http://localhost:9001`)에서 USD 파일 업로드 확인

### 5-3. USD 수정 후 재백업

1. Nucleus에서 대상 USD 파일의 Prim 속성 변경 (예: Jetbot Position X를 2.0으로)
2. `nucleus_pipeline --nucleus-path` 재실행
3. Dashboard에서 두 시점 비교

**확인 사항:**
- [ ] 재백업 성공
- [ ] Dashboard Entity Diff에서 해당 Entity가 "changed"로 표시
- [ ] Entity Sub-Prim drill-down에서 변경된 속성 확인 가능

### 5-4. Task 3 — KKR.TimeTravel Extension (Stage 복원)

Isaac Sim에서 백업 시점 기반으로 Stage를 복원합니다.

1. Isaac Sim 실행
2. Extension Manager (Window > Extensions)에서 `KKR.TimeTravel` 검색 후 활성화
3. Tools > KKR-Tools > KKR.TimeTravel 클릭하여 Extension 패널 열기
4. **API URL** 드롭다운에서 `Local (localhost:8100)` 선택
5. **"Load Times"** 버튼 클릭 → 백업 시점 목록 로드
6. 복원할 시점 선택
7. **"Load Entities"** 버튼 클릭 → Entity 목록 로드
8. 복원할 Entity 선택 후 **"Restore"** 클릭

**확인 사항:**
- [ ] 백업 시점 목록이 정상 로드됨
- [ ] Entity 목록이 해당 시점 기준으로 표시됨
- [ ] 복원 후 Stage에 이전 버전 상태가 반영됨
- [ ] Status/Log에 복원 모드 (Changes Only / Full Entity / Full All) 표시
- [ ] Undo 버튼으로 복원 전 상태로 되돌리기 가능
---

## Phase 6: Iceberg 데이터 검증 (자동 실행 완료)

### 6-1. 테이블 데이터 현황

| 테이블 | 레코드 수 | 비고 |
|--------|-----------|------|
| entities | 7 | 3개 백업 시점 x 2~3 entities |
| prim_snapshots | 5 | Jetbot Sub-Prims (Camera, Lidar) |
| raw_backup_files | N | nucleus_pipeline Task 1 백업 파일 메타데이터 |

### 6-2. Trino SQL 직접 확인

```bash
# Entity 전체 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT entity_path, entity_hash, backup_time FROM polaris.netai.entities ORDER BY backup_time, entity_path"}'

# Prim Snapshot 조회
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT entity_path, relative_path, prim_hash FROM polaris.netai.prim_snapshots ORDER BY entity_path, relative_path"}'

# Dynamic IoT 최신 데이터
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM polaris.netai.raw_backup_files ORDER BY backup_time DESC LIMIT 5"}'
```

---

## 테스트 요약

| Phase | 항목 | 방법 | 결과 |
|-------|------|------|------|
| 1 | Docker 서비스 | 자동 | PASS (5/5 healthy) |
| 2 | API 6개 엔드포인트 | 자동 | PASS (6/6) |
| 3 | 보안 (SQL injection) | 자동 | PASS |
| 4-1 | Dashboard 접근 | 자동 | PASS (HTTP 200) |
| 4-2 | Dashboard Entity Diff UI | **수동** | 브라우저에서 확인 필요 |
| 5 | Isaac Sim Extension | **수동** | Isaac Sim 환경 필요 |
| 6 | Iceberg 데이터 검증 | 자동 | PASS |

**자동 테스트 결과: 8/8 PASS**
**수동 테스트: 2개 Phase 남음 (Dashboard UI 확인 + Isaac Sim Extension)**
