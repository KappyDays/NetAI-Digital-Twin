# End-to-End Scenario Guide

Nucleus Pipeline (Task 1, 2) + KKR.TimeTravel Extension (Task 3)을 활용한 대표적 사용 시나리오.

## Prerequisites

| 항목 | 상세 |
|------|------|
| Lakehouse Stack | `cd Lakehouse/Iceberg && ./start.sh` (Polaris, MinIO, Trino, API, Dashboard) |
| Nucleus Server | `omniverse://10.38.38.48` 접근 가능 |
| Isaac Sim 5.1.0 | KKR.TimeTravel Extension 활성화 |
| Python 환경 | `nucleus_pipeline/` 실행 가능 (pxr, omni.client) |
| Python 환경 활성화 | `.\.venv\Scripts\activate`

**Lakehouse API 접속 확인:**

```bash
curl http://localhost:8100/api/v1/health
# {"status": "ok"}
```

**Trino 직접 접속 (선택):**

```bash
# Trino CLI 또는 DBeaver 등 SQL 클라이언트로 접속
# Host: localhost:8900, Catalog: polaris, Schema: netai
```

**Iceberg 테이블 조회 공통 방법:**

모든 Iceberg 조회는 아래 3가지 방법 중 하나를 사용한다:

| 방법 | 설명 | 사용 시점 |
|------|------|----------|
| **Dashboard** | `http://localhost:3000` → Entities / Raw Backup 페이지 | 시각적 확인, Diff 비교 |
| **API Query** | `POST http://localhost:8100/api/v1/query` (body: `{"sql": "..."}`) | 프로그래밍, 자동화 |
| **Trino CLI** | `localhost:8900`에 SQL 클라이언트 접속 | 자유 SQL, 디버깅 |

```bash
# API Query 예시 (curl)
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM polaris.netai.entities LIMIT 5"}'
```

---

## Iceberg 테이블 스키마 참조

### raw_backup_files

```sql
CREATE TABLE polaris.netai.raw_backup_files (
    backup_time   TIMESTAMP(6),  -- 백업 실행 시각
    folder_path   VARCHAR,       -- Nucleus 폴더 경로
    file_path     VARCHAR,       -- 파일 전체 경로
    file_name     VARCHAR,       -- 파일명
    file_extension VARCHAR,      -- 확장자
    file_size     BIGINT,        -- 바이트 단위
    modified_time VARCHAR,       -- Nucleus 수정 시각
    s3_key        VARCHAR,       -- MinIO 저장 경로
    status        VARCHAR,       -- new | modified | deleted | unchanged
    backup_source VARCHAR        -- 백업 소스 라벨
) WITH (partitioning = ARRAY['day(backup_time)'])
```

### entities

```sql
CREATE TABLE polaris.netai.entities (
    entity_id     VARCHAR,       -- UUID
    entity_path   VARCHAR,       -- /World/AI_Grad_Building
    entity_type   VARCHAR,       -- Xform, Scope 등
    source_type   VARCHAR,       -- payload, root 등
    source_asset  VARCHAR,       -- 원본 USD 경로
    is_dynamic    BOOLEAN,       -- 동적 Entity 여부
    dynamic_table VARCHAR,       -- 동적 데이터 테이블명
    child_count   INTEGER,       -- 하위 Prim 수
    entity_hash   VARCHAR,       -- 전체 해시
    usd_file_path VARCHAR,       -- MinIO USD 경로
    backup_source VARCHAR,       -- nucleus | local
    backup_time   TIMESTAMP(6)   -- 백업 시각
) WITH (partitioning = ARRAY['day(backup_time)'])
```

### prim_snapshots

```sql
CREATE TABLE polaris.netai.prim_snapshots (
    entity_path   VARCHAR,       -- 소속 Entity 경로
    relative_path VARCHAR,       -- Entity 기준 상대 경로
    prim_type     VARCHAR,       -- Mesh, Xform 등
    properties    VARCHAR,       -- JSON 문자열 (property key-value)
    prim_hash     VARCHAR,       -- Prim 해시
    backup_time   TIMESTAMP(6)   -- 백업 시각
) WITH (partitioning = ARRAY['day(backup_time)'])
```

---

## Scenario 1: Raw Folder Backup (Task 1)

> Nucleus 서버의 프로젝트 폴더를 **통째로** MinIO에 증분 백업한다.
> USD 파일뿐 아니라 텍스처, 머티리얼, 레퍼런스 파일 등 모든 파일을 보존한다.

### 1-1. 최초 전체 백업

```bash
cd nucleus_pipeline

python main.py \
  --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Dream-AI+Twin/" \
  --api-url http://localhost:8100
```

**실행 흐름:**

1. **Scan** — Nucleus 폴더 하위 모든 파일 재귀 탐색 (`omni.client.list`)
2. **Compare** — Iceberg `raw_backup_files` 테이블에서 이전 백업 조회 → 최초이므로 전부 `new`
3. **Download** — 변경분(new + modified) 파일을 로컬 임시 디렉토리로 다운로드
4. **Upload to MinIO** — `raw-backups/{folder_name}/{timestamp}/` 경로로 S3 업로드
5. **Record to Iceberg** — 파일별 메타데이터(path, size, modified_time, status) INSERT
6. **Summary** — 처리 결과 출력

**예상 출력:**

```
=== Raw Backup Summary ===
  Folder: omniverse://10.38.38.48/Projects/Dream-AI+Twin/
  Backup time: 2026-03-31T10:00:00.000000
  Total files scanned: 446
  New: 446 | Modified: 0 | Deleted: 0 | Unchanged: 0
  Uploaded: 446 files to MinIO
  Recorded: 446 entries to Iceberg
```

**Iceberg 확인 — 백업된 파일 목록 조회:**

```sql
-- 방금 백업된 파일 목록 확인
SELECT file_path, file_size, status, s3_key
FROM polaris.netai.raw_backup_files
WHERE backup_time = TIMESTAMP '2026-03-31 10:00:00'
ORDER BY file_path
LIMIT 20;
```

```sql
-- 파일 확장자별 통계
SELECT file_extension, COUNT(*) AS cnt, SUM(file_size) AS total_bytes
FROM polaris.netai.raw_backup_files
WHERE backup_time = TIMESTAMP '2026-03-31 10:00:00'
GROUP BY file_extension
ORDER BY total_bytes DESC;
```

| file_extension | cnt | total_bytes |
|----------------|-----|-------------|
| .usd | 12 | 48,329,472 |
| .png | 187 | 32,104,560 |
| .mdl | 45 | 2,340,128 |
| ... | ... | ... |

```sql
-- 전체 백업 건수 확인
SELECT COUNT(*) AS total_files,
       SUM(file_size) AS total_bytes,
       COUNT(DISTINCT file_extension) AS extension_types
FROM polaris.netai.raw_backup_files
WHERE backup_time = TIMESTAMP '2026-03-31 10:00:00';
```

### 1-2. 증분 백업 (파일 수정 후)

Nucleus에서 텍스처 파일을 교체하거나 USD 파일을 수정한 뒤 동일 명령 재실행:

```bash
python main.py \
  --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Dream-AI+Twin/" \
  --api-url http://localhost:8100
```

**증분 판별 기준:** `modified_time` 비교 (이전 백업의 Iceberg 레코드 vs 현재 Nucleus 파일)

**예상 출력:**

```
=== Raw Backup Summary ===
  Folder: omniverse://10.38.38.48/Projects/Dream-AI+Twin/
  Backup time: 2026-03-31T14:30:00.000000
  Total files scanned: 448
  New: 2 | Modified: 3 | Deleted: 1 | Unchanged: 442
  Uploaded: 5 files to MinIO (new + modified only)
  Recorded: 448 entries to Iceberg
```

**Iceberg 확인 — 증분 변경분 조회:**

```sql
-- 변경된 파일만 조회 (new + modified + deleted)
SELECT file_path, status, file_size, modified_time
FROM polaris.netai.raw_backup_files
WHERE backup_time = TIMESTAMP '2026-03-31 14:30:00'
  AND status != 'unchanged'
ORDER BY status, file_path;
```

| file_path | status | file_size | modified_time |
|-----------|--------|-----------|---------------|
| /Projects/.../new_texture.png | new | 1,024,000 | 2026-03-31T13:20:00 |
| /Projects/.../wall_mat.mdl | modified | 8,192 | 2026-03-31T12:45:00 |
| /Projects/.../old_asset.usd | deleted | 0 | — |

```sql
-- 두 시점 간 status 분포 비교
SELECT status, COUNT(*) AS cnt
FROM polaris.netai.raw_backup_files
WHERE backup_time = TIMESTAMP '2026-03-31 14:30:00'
GROUP BY status
ORDER BY cnt DESC;
```

| status | cnt |
|--------|-----|
| unchanged | 442 |
| modified | 3 |
| new | 2 |
| deleted | 1 |

### 1-3. Dashboard에서 백업 이력 확인

1. 브라우저에서 `http://localhost:3000` 접속
2. 좌측 메뉴 **Raw Backup** 클릭
3. 폴더별 백업 스냅샷 목록 확인
4. 두 시점 선택 → **Diff** 비교 (New / Modified / Deleted 카운터)

**Iceberg 확인 — 백업 시점 타임라인:**

```sql
-- 전체 백업 시점 목록 + 폴더별 파일 수
SELECT backup_time, folder_path,
       COUNT(*) AS total_files,
       SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS new_cnt,
       SUM(CASE WHEN status = 'modified' THEN 1 ELSE 0 END) AS modified_cnt,
       SUM(CASE WHEN status = 'deleted' THEN 1 ELSE 0 END) AS deleted_cnt
FROM polaris.netai.raw_backup_files
GROUP BY backup_time, folder_path
ORDER BY backup_time DESC;
```

| backup_time | folder_path | total_files | new_cnt | modified_cnt | deleted_cnt |
|-------------|-------------|-------------|---------|--------------|-------------|
| 2026-03-31 14:30:00 | /Projects/Dream-AI+Twin/ | 448 | 2 | 3 | 1 |
| 2026-03-31 10:00:00 | /Projects/Dream-AI+Twin/ | 446 | 446 | 0 | 0 |

### 1-4. 복수 폴더 독립 백업

```bash
# 프로젝트 A
python main.py --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Dream-AI+Twin/"

# 프로젝트 B (독립적 백업 이력)
python main.py --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Another-Project/"
```

각 폴더는 `folder_path` 컬럼으로 분리되어 독립적인 백업 타임라인을 가진다.

**Iceberg 확인 — 폴더별 백업 현황:**

```sql
-- 폴더별 백업 횟수와 최신 백업 시각
SELECT folder_path,
       COUNT(DISTINCT backup_time) AS backup_count,
       MAX(backup_time) AS latest_backup,
       SUM(file_size) / 1048576 AS total_mb
FROM polaris.netai.raw_backup_files
GROUP BY folder_path;
```

---

## Scenario 2: Entity Prim Property Backup (Task 2)

> Nucleus의 USD 파일을 열어 **Root Layer Override** (사용자가 수정한 Property 값)만
> 추출하여 Iceberg에 저장한다. Entity별 3-Level 드릴다운 구조로 시점간 Diff 비교가 가능하다.

### 2-1. 최초 Entity 백업

```bash
cd nucleus_pipeline

python main.py \
  --nucleus-path "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd" \
  --api-url http://localhost:8100
```

**실행 흐름:**

1. **Download** — Nucleus에서 USD 파일 + 참조 Entity USD 다운로드
2. **Parse** — `Sdf.Layer.FindOrOpen()`으로 Root Layer Override 추출 (composed value가 아닌 **사용자 수정값만**)
3. **Structure** — /World 하위 Entity별로 그룹핑 (3-Level: Entity → Prim → Property)
4. **Upload** — Entity USD 파일을 MinIO에 업로드 (`--skip-usd-upload`로 생략 가능)
5. **Record** — `entities` + `prim_snapshots` 테이블에 INSERT
6. **Summary** — Entity 수, Prim 수, Property 수 출력

**예상 출력:**

```
=== Entity Backup Summary ===
  Source: omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd
  Backup time: 2026-03-31T10:05:00.000000
  Entities: 6
  Prim snapshots: 142
  Total properties: 1,247
```

**Entity 구조 예시:**

```
/World
  /World/AI_Grad_Building        → Entity (entity_type: Xform)
    /World/AI_Grad_Building/Mesh_01   → Prim (properties: xformOp:translate, ...)
    /World/AI_Grad_Building/Mesh_02   → Prim
  /World/Environment             → Entity (entity_type: Xform)
    /World/Environment/Sky        → Prim
  /World/Parking_Lot             → Entity
  ...
```

**Iceberg 확인 — 백업된 Entity 목록:**

```sql
-- 어떤 Entity들이 백업되었는가?
SELECT entity_path, entity_type, child_count, entity_hash, backup_source
FROM polaris.netai.entities
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00'
ORDER BY entity_path;
```

| entity_path | entity_type | child_count | entity_hash | backup_source |
|-------------|-------------|-------------|-------------|---------------|
| World/AI_Grad_Building | Xform | 28 | a3f2c1... | nucleus |
| World/Environment | Xform | 15 | b7d4e2... | nucleus |
| World/Parking_Lot | Xform | 34 | c9e1a5... | nucleus |
| ... | ... | ... | ... | ... |

**Iceberg 확인 — 특정 Entity의 Prim 스냅샷:**

```sql
-- AI_Grad_Building Entity 하위 Prim과 Property 확인
SELECT relative_path, prim_type, prim_hash,
       LENGTH(properties) AS props_json_length
FROM polaris.netai.prim_snapshots
WHERE entity_path = 'World/AI_Grad_Building'
  AND backup_time = TIMESTAMP '2026-03-31 10:05:00'
ORDER BY relative_path
LIMIT 10;
```

| relative_path | prim_type | prim_hash | props_json_length |
|---------------|-----------|-----------|-------------------|
| World/AI_Grad_Building | Xform | d1a2b3... | 456 |
| World/AI_Grad_Building/Mesh_01 | Mesh | e4f5a6... | 1,234 |
| World/AI_Grad_Building/Mesh_02 | Mesh | f7c8d9... | 892 |

**Iceberg 확인 — Property JSON 내용 직접 확인:**

```sql
-- 특정 Prim의 실제 Override Property 값 조회
SELECT relative_path, properties
FROM polaris.netai.prim_snapshots
WHERE entity_path = 'World/AI_Grad_Building'
  AND relative_path = 'World/AI_Grad_Building/Mesh_01'
  AND backup_time = TIMESTAMP '2026-03-31 10:05:00';
```

`properties` 컬럼은 JSON 문자열로, 예시:

```json
{
  "xformOp:translate": [120.5, 0.0, -45.3],
  "xformOp:orient": [1.0, 0.0, 0.0, 0.0],
  "xformOp:scale": [1.0, 1.0, 1.0],
  "visibility": "inherited"
}
```

### 2-2. 수정 후 2차 백업 → Diff 비교

Isaac Sim에서 건물 위치를 이동하거나 Property를 변경한 뒤 저장, 다시 백업:

```bash
python main.py \
  --nucleus-path "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd" \
  --api-url http://localhost:8100
```

**API로 Diff 조회:**

```bash
# Entity-Level Diff (어떤 Entity가 변경되었는가?)
curl "http://localhost:8100/api/v1/entities/diff?time_a=2026-03-31T10:05:00&time_b=2026-03-31T14:30:00"
```

```json
{
  "added": [],
  "removed": [],
  "changed": ["World/AI_Grad_Building"],
  "unchanged": ["World/Environment", "World/Parking_Lot", ...]
}
```

```bash
# Prim-Level Diff (Entity 안에서 어떤 Prim이 변경되었는가?)
curl "http://localhost:8100/api/v1/entities/World%2FAI_Grad_Building/prim-diff?time_a=2026-03-31T10:05:00&time_b=2026-03-31T14:30:00"
```

```json
{
  "added": [],
  "removed": [],
  "changed": ["World/AI_Grad_Building/Mesh_01"],
  "unchanged": ["World/AI_Grad_Building/Mesh_02"]
}
```

**Iceberg 확인 — 두 시점 간 Entity 해시 비교 (Diff의 원리):**

```sql
-- Diff가 내부적으로 수행하는 해시 비교를 직접 확인
SELECT
    COALESCE(a.entity_path, b.entity_path) AS entity_path,
    a.entity_hash AS hash_time_a,
    b.entity_hash AS hash_time_b,
    CASE
        WHEN a.entity_hash IS NULL THEN 'added'
        WHEN b.entity_hash IS NULL THEN 'removed'
        WHEN a.entity_hash != b.entity_hash THEN 'changed'
        ELSE 'unchanged'
    END AS diff_status
FROM
    (SELECT entity_path, entity_hash FROM polaris.netai.entities
     WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00') a
FULL OUTER JOIN
    (SELECT entity_path, entity_hash FROM polaris.netai.entities
     WHERE backup_time = TIMESTAMP '2026-03-31 14:30:00') b
ON a.entity_path = b.entity_path
ORDER BY entity_path;
```

| entity_path | hash_time_a | hash_time_b | diff_status |
|-------------|-------------|-------------|-------------|
| World/AI_Grad_Building | a3f2c1... | **x7k9m2...** | **changed** |
| World/Environment | b7d4e2... | b7d4e2... | unchanged |
| World/Parking_Lot | c9e1a5... | c9e1a5... | unchanged |

**Iceberg 확인 — 변경된 Property 값 비교:**

```sql
-- AI_Grad_Building/Mesh_01의 두 시점 Property 값을 나란히 비교
SELECT
    a.relative_path,
    a.properties AS props_10h,
    b.properties AS props_14h
FROM
    (SELECT relative_path, properties FROM polaris.netai.prim_snapshots
     WHERE entity_path = 'World/AI_Grad_Building'
       AND relative_path = 'World/AI_Grad_Building/Mesh_01'
       AND backup_time = TIMESTAMP '2026-03-31 10:05:00') a
JOIN
    (SELECT relative_path, properties FROM polaris.netai.prim_snapshots
     WHERE entity_path = 'World/AI_Grad_Building'
       AND relative_path = 'World/AI_Grad_Building/Mesh_01'
       AND backup_time = TIMESTAMP '2026-03-31 14:30:00') b
ON a.relative_path = b.relative_path;
```

```
props_10h: {"xformOp:translate": [120.5, 0.0, -45.3], ...}
props_14h: {"xformOp:translate": [150.0, 0.0, -45.3], ...}  ← X좌표 변경!
```

**Iceberg 확인 — Entity 백업 시점 이력:**

```sql
-- 전체 백업 시점별 Entity 수
SELECT backup_time, backup_source,
       COUNT(*) AS entity_count,
       SUM(child_count) AS total_prims
FROM polaris.netai.entities
GROUP BY backup_time, backup_source
ORDER BY backup_time DESC;
```

| backup_time | backup_source | entity_count | total_prims |
|-------------|---------------|--------------|-------------|
| 2026-03-31 14:30:00 | nucleus | 6 | 142 |
| 2026-03-31 10:05:00 | nucleus | 6 | 142 |

### 2-3. USD 업로드 생략 옵션

Property 변경 추적만 필요하고 USD 파일 자체의 MinIO 업로드가 불필요할 때:

```bash
python main.py \
  --nucleus-path "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd" \
  --skip-usd-upload
```

**Iceberg 확인 — usd_file_path가 비어 있는지 확인:**

```sql
SELECT entity_path, usd_file_path
FROM polaris.netai.entities
WHERE backup_time = TIMESTAMP '2026-03-31 15:00:00';
-- usd_file_path = NULL (업로드 생략됨)
```

---

## Scenario 3: Time Travel Restore (Task 3 — KKR.TimeTravel Extension)

> Isaac Sim에서 KKR.TimeTravel Extension을 사용하여
> Iceberg에 저장된 과거 백업 시점으로 현재 Stage를 복원한다.

### 사전 조건

- Scenario 2에서 **2회 이상** Entity 백업이 완료된 상태
- Isaac Sim에서 Dream-AI_Plus_Twin.usd가 열린 상태
- KKR.TimeTravel Extension 활성화 (Tools > KKR-Tools > KKR.TimeTravel)

### 3-1. API 연결 설정

1. **API Settings** 프레임을 연다
2. 환경에 맞는 Preset 버튼 클릭:
   - **Local (localhost:8100)** — Windows에서 Isaac Sim 직접 실행 시
   - **Docker (lakehouse-api:8000)** — Docker Compose 내부 네트워크
3. **TEST CONNECTION** 클릭
4. Status Log에 `[OK] API connected: ok` 확인

### 3-2. 백업 시점 탐색

1. **Backup Timeline** 프레임에서 **LOAD BACKUP TIMES** 클릭
2. `[1/3] Source: nucleus` 형태로 시점 표시
3. **<< / >>** 버튼으로 시점 탐색
4. 선택한 시점과 최신 백업 간 **Diff 미리보기** 자동 표시:
   ```
   Diff vs latest: Changed=1, Added=0, Removed=0, Unchanged=5
   ```

**Iceberg 확인 — Extension이 내부적으로 호출하는 데이터:**

```sql
-- LOAD BACKUP TIMES가 조회하는 데이터
SELECT DISTINCT backup_time, backup_source
FROM polaris.netai.entities
ORDER BY backup_time DESC;
```

```sql
-- Diff 미리보기가 사용하는 Entity 해시 비교
SELECT entity_path, entity_hash
FROM polaris.netai.entities
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00';
```

### 3-3. Stage 전체 복원 (3가지 모드)

**Backup Timeline**에서 복원할 시점을 선택한 뒤 **Stage Restore** 프레임으로 이동.

#### Mode 1: Changes Only (기본, 가장 안전)

- 백업된 Override만 현재 Stage에 적용
- 기존 Prim 삭제 없음
- 사용 시점: "수정된 Property만 되돌리고 싶다"

1. **Changes Only (safe)** 라디오 선택
2. **Restore Stage** 클릭
3. 결과 확인:
   ```
   Restored 6 entities
   Properties applied: 1,247
   Properties failed: 0
   Prims deleted: 0
   ```

**Iceberg 확인 — 복원에 사용된 전체 데이터 조회:**

```sql
-- restore-all 엔드포인트가 반환하는 Entity 목록
SELECT entity_path, entity_type, child_count
FROM polaris.netai.entities
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00';

-- 해당 시점의 모든 Prim 스냅샷 (= Stage에 적용되는 Override)
SELECT entity_path, relative_path, prim_type, properties
FROM polaris.netai.prim_snapshots
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00'
ORDER BY entity_path, relative_path;
```

#### Mode 2: Full Restore — Entity (Looks/Camera 보호)

- 백업에 없는 **Entity Prim** 삭제 + Override 적용
- Looks, Camera_presets 등 **비-Entity Scope**는 보호
- 사용 시점: "백업 시점과 동일한 Entity 구성으로 맞추되, 머티리얼은 유지"

1. **Full Restore — Entity** 라디오 선택
2. **Restore Stage** 클릭

#### Mode 3: Full Restore — All (경고 포함)

- /World 하위 **모든** 비-백업 Prim 삭제 + Override 적용
- Looks, Camera_presets **포함** 삭제
- 사용 시점: "백업 시점의 완전한 상태로 되돌리고 싶다"

1. **Full Restore — All** 라디오 선택
2. **Restore Stage** 클릭 → **경고 메시지** 표시:
   ```
   *** CONFIRM: Full Restore (All) mode selected ***
   This will delete Looks, Camera_presets, and all non-backup Prims.
   Click 'Restore Stage' again to proceed, or change mode to cancel.
   ```
3. **Restore Stage** 다시 클릭하여 확인

### 3-4. Entity 단위 복원

특정 Entity만 선택적으로 복원할 때:

1. **Entity Restore** 프레임에서 **LOAD ENTITIES** 클릭
2. **<< / >>** 버튼으로 Entity 탐색: `/World/AI_Grad_Building`
3. **Restore Entity** 클릭
4. 해당 Entity의 Override만 현재 Stage에 적용
   ```
   Entity restored: 24 properties applied, 0 failed
   ```

**Iceberg 확인 — 단일 Entity 복원 데이터:**

```sql
-- Extension이 restore 시 가져오는 단일 Entity의 Prim 스냅샷
SELECT relative_path, prim_type, properties
FROM polaris.netai.prim_snapshots
WHERE entity_path = 'World/AI_Grad_Building'
  AND backup_time = TIMESTAMP '2026-03-31 10:05:00'
ORDER BY relative_path;
```

### 3-5. Undo (복원 전 상태로 되돌리기)

복원 실행 전에 자동으로 **Undo 스냅샷**이 캡처된다 (Root Layer Override → Python dict).

1. 복원 후 결과가 만족스럽지 않으면 **Undo** 버튼 클릭
2. 복원 직전 상태로 Stage가 되돌아감
   ```
   Undo complete: 1,247 properties restored, 0 failed
   ```

> **Note:** 1단계 Undo만 지원. Undo 실행 후 스냅샷은 소거되며, Extension 재시작 시에도 소실된다.
> Undo 스냅샷은 메모리(Python dict)에만 저장되며, Iceberg에는 기록되지 않는다.

### 3-6. Nucleus Reopen (원본 파일 다시 열기)

Override 복원이 아닌, Nucleus에 저장된 **원본 USD 파일 자체**를 다시 열고 싶을 때:

1. **Nucleus** 프레임에서 **Reopen from Nucleus** 클릭
2. 현재 Stage의 파일 경로(`omniverse://10.38.38.48/...`)를 자동 감지하여 재오픈
3. **주의:** 저장하지 않은 Override 변경사항은 모두 소실됨

---

## 통합 시나리오: 일일 운영 워크플로우

실제 운영에서 Task 1 → Task 2 → Task 3을 조합하는 대표적 흐름:

### 오전: 작업 시작 전 백업

```bash
# 1. Raw 폴더 전체 백업 (텍스처, 머티리얼, 참조 파일 포함)
python main.py --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Dream-AI+Twin/"

# 2. Entity Property 백업 (Root Layer Override 추적)
python main.py \
  --nucleus-path "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd"
```

**Iceberg 확인 — 오전 백업 상태 전체 요약:**

```sql
-- 오늘 실행된 모든 백업 한눈에 보기
SELECT 'raw_backup' AS type, backup_time, COUNT(*) AS records
FROM polaris.netai.raw_backup_files
WHERE backup_time >= CURRENT_DATE
GROUP BY backup_time
UNION ALL
SELECT 'entity' AS type, backup_time, COUNT(*) AS records
FROM polaris.netai.entities
WHERE backup_time >= CURRENT_DATE
GROUP BY backup_time
ORDER BY backup_time DESC;
```

| type | backup_time | records |
|------|-------------|---------|
| raw_backup | 2026-03-31 10:00:00 | 446 |
| entity | 2026-03-31 10:05:00 | 6 |

### 오후: 작업 중 실수 발생 → 복원

Isaac Sim에서 건물을 잘못 이동하거나 Property를 잘못 수정한 경우:

1. **KKR.TimeTravel** Extension 열기
2. **LOAD BACKUP TIMES** → 오전 백업 시점 선택
3. **Diff 미리보기**로 변경 범위 확인
4. **Changes Only** 모드로 **Restore Stage** → 수정된 Property만 오전 시점으로 복원
5. 결과 불만족 시 **Undo**로 즉시 되돌리기

### 퇴근 전: 최종 백업

```bash
# 최종 상태 백업
python main.py --raw-backup \
  --nucleus-folder "omniverse://10.38.38.48/Projects/Dream-AI+Twin/"
python main.py \
  --nucleus-path "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI_Plus_Twin.usd"
```

**Iceberg 확인 — 하루 전체 이력 리뷰:**

```sql
-- 오늘 하루 동안의 Entity 변경 추적
SELECT a.backup_time, a.entity_path, a.entity_hash,
       LAG(a.entity_hash) OVER (
           PARTITION BY a.entity_path ORDER BY a.backup_time
       ) AS prev_hash
FROM polaris.netai.entities a
WHERE a.backup_time >= CURRENT_DATE
ORDER BY a.entity_path, a.backup_time;
```

### Dashboard에서 변경 이력 검토

`http://localhost:3000` 에서:
- **Entities** 페이지: Entity Diff 3-Level 드릴다운 (Entity → Prim → Property)
- **Raw Backup** 페이지: 파일 수준 변경 추적 (New / Modified / Deleted)

---

## API Quick Reference

### Entity Backup API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/entities/backup` | Entity + Prim 스냅샷 저장 |
| `GET` | `/api/v1/entities/backup-times` | 백업 시점 목록 |
| `GET` | `/api/v1/entities/list?backup_time=T` | 시점별 Entity 목록 |
| `GET` | `/api/v1/entities/diff?time_a=T1&time_b=T2` | Entity-Level Diff |
| `GET` | `/api/v1/entities/{path}/prim-diff?time_a=T1&time_b=T2` | Prim-Level Diff |
| `GET` | `/api/v1/entities/{path}/restore?backup_time=T` | 단일 Entity 복원 데이터 |
| `GET` | `/api/v1/entities/restore-all?backup_time=T` | 전체 Entity 복원 데이터 |

### Raw Backup API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/raw-backup/files` | 파일 메타데이터 저장 |
| `GET` | `/api/v1/raw-backup/latest-files?folder_path=P` | 최신 백업 파일 목록 |
| `GET` | `/api/v1/raw-backup/list?backup_time=T` | 시점별 파일 목록 |
| `GET` | `/api/v1/raw-backup/times` | 백업 시점 목록 (폴더별) |
| `GET` | `/api/v1/raw-backup/diff?time_a=T1&time_b=T2` | 파일 Diff |

### Ad-hoc Trino Query API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/query` | 임의 SQL 실행 (`{"sql": "SELECT ..."}`) |

**응답 형식:**
```json
{
  "columns": ["entity_path", "entity_type"],
  "rows": [["World/AI_Grad_Building", "Xform"], ...],
  "row_count": 6
}
```

### CLI Commands

```bash
# Task 1: Raw Folder Backup
python main.py --raw-backup --nucleus-folder <URI> [--api-url URL]

# Task 2: Entity Property Backup
python main.py --nucleus-path <URI> [--api-url URL] [--skip-usd-upload]

# Nucleus Client (단독 사용)
python nucleus_client.py --list-folder <URI> [TOKEN]
python nucleus_client.py --download-files <JSON|@file> <DEST> [TOKEN]
```

---

## Appendix: Iceberg 테이블 전체 조회 튜토리얼

이 프로젝트에서 생성되는 **모든** Iceberg 테이블을 조회하고 데이터를 확인하는 방법.

### 조회 방법

```bash
# 방법 1: Lakehouse API (가장 간편)
curl -X POST http://localhost:8100/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SHOW TABLES FROM polaris.netai"}'

# 방법 2: Dashboard
# http://localhost:3000 → 각 페이지에서 시각적 확인

# 방법 3: Trino CLI / DBeaver
# Host: localhost:8900, Catalog: polaris, Schema: netai
```

### 테이블 목록

```sql
SHOW TABLES FROM polaris.netai;
```

| 테이블 | 생성 기능 | 파티셔닝 |
|--------|----------|----------|
| `raw_backup_files` | Nucleus Pipeline — Task 1 Raw 백업 | `day(backup_time)` |
| `entities` | Nucleus Pipeline — Task 2 Entity 백업 | `day(backup_time)` |
| `prim_snapshots` | Nucleus Pipeline — Task 2 Prim 백업 | `day(backup_time)` |

---

### 1. entities — Entity 백업 레코드

Nucleus Pipeline `--nucleus-path` 또는 `POST /api/v1/entities/backup`으로 생성.
/World 하위 최상위 Entity 단위로 백업 메타데이터를 저장한다.

> 이 테이블은 위 Scenario 2에서 상세히 다루었으므로, 여기서는 추가 활용 쿼리만 소개한다.

**추가 조회 예시:**

```sql
-- 전체 백업 이력에서 특정 Entity의 해시 변경 추적 (변경 발생 시점 찾기)
SELECT backup_time, entity_hash, backup_source
FROM polaris.netai.entities
WHERE entity_path = 'World/AI_Grad_Building'
ORDER BY backup_time;
```

| backup_time | entity_hash | backup_source |
|-------------|-------------|---------------|
| 2026-03-31 10:05:00 | a3f2c1... | nucleus |
| 2026-03-31 14:30:00 | **x7k9m2...** | nucleus |
| 2026-03-31 18:00:00 | x7k9m2... | nucleus |

→ 10:05 ~ 14:30 사이에 변경 발생, 14:30 이후로는 동일

```sql
-- 가장 자주 변경된 Entity Top 5
SELECT entity_path, COUNT(DISTINCT entity_hash) AS unique_versions
FROM polaris.netai.entities
GROUP BY entity_path
ORDER BY unique_versions DESC
LIMIT 5;
```

```sql
-- 특정 날짜의 백업에서 Dynamic Entity만 조회
SELECT entity_path, dynamic_table, child_count
FROM polaris.netai.entities
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00'
  AND is_dynamic = true;
```

---

### 2. prim_snapshots — Prim Property 스냅샷

Entity 백업과 동시에 생성. 각 Entity 하위 Prim의 Override Property를 JSON으로 저장한다.

> 이 테이블은 위 Scenario 2에서 상세히 다루었으므로, 여기서는 추가 활용 쿼리만 소개한다.

**추가 조회 예시:**

```sql
-- 전체 Prim 스냅샷에서 xformOp:translate가 포함된 Prim 검색
SELECT entity_path, relative_path, properties
FROM polaris.netai.prim_snapshots
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00'
  AND properties LIKE '%xformOp:translate%'
LIMIT 10;
```

```sql
-- Entity별 스냅샷 수 (어떤 Entity의 Override가 가장 많은지)
SELECT entity_path, COUNT(*) AS prim_count,
       SUM(LENGTH(properties)) AS total_props_bytes
FROM polaris.netai.prim_snapshots
WHERE backup_time = TIMESTAMP '2026-03-31 10:05:00'
GROUP BY entity_path
ORDER BY prim_count DESC;
```

```sql
-- 두 시점에서 동일 Prim의 Property 차이 직접 비교
SELECT a.relative_path,
       a.prim_hash AS hash_before,
       b.prim_hash AS hash_after,
       a.properties AS props_before,
       b.properties AS props_after
FROM polaris.netai.prim_snapshots a
JOIN polaris.netai.prim_snapshots b
  ON a.entity_path = b.entity_path
 AND a.relative_path = b.relative_path
WHERE a.backup_time = TIMESTAMP '2026-03-31 10:05:00'
  AND b.backup_time = TIMESTAMP '2026-03-31 14:30:00'
  AND a.prim_hash != b.prim_hash;
```

---

### 3. raw_backup_files — Nucleus 폴더 Raw 백업

Nucleus Pipeline `--raw-backup` 또는 `POST /api/v1/raw-backup/files`로 생성.
Nucleus 폴더의 모든 파일에 대한 메타데이터와 증분 상태를 저장한다.

> 이 테이블은 위 Scenario 1에서 상세히 다루었으므로, 여기서는 추가 활용 쿼리만 소개한다.

**추가 조회 예시:**

```sql
-- 특정 파일의 전체 변경 이력 (언제 추가되고, 언제 수정되었는가)
SELECT backup_time, status, file_size, modified_time, s3_key
FROM polaris.netai.raw_backup_files
WHERE file_path = '/Projects/Dream-AI+Twin/Materials/wall_texture.png'
ORDER BY backup_time;
```

| backup_time | status | file_size | modified_time | s3_key |
|-------------|--------|-----------|---------------|--------|
| 2026-03-31 10:00:00 | new | 1,024,000 | 2026-03-30T09:00:00 | raw-backups/Dream-AI+Twin/.../ |
| 2026-03-31 14:30:00 | modified | 1,128,000 | 2026-03-31T12:45:00 | raw-backups/Dream-AI+Twin/.../ |
| 2026-03-31 18:00:00 | unchanged | 1,128,000 | 2026-03-31T12:45:00 | — |

```sql
-- 삭제된 파일만 추적 (어떤 파일이 사라졌는가)
SELECT backup_time, file_path, file_name
FROM polaris.netai.raw_backup_files
WHERE status = 'deleted'
ORDER BY backup_time DESC;
```

```sql
-- 일별 백업 용량 추이
SELECT CAST(backup_time AS DATE) AS backup_date,
       folder_path,
       COUNT(*) AS file_count,
       SUM(file_size) / 1048576 AS total_mb
FROM polaris.netai.raw_backup_files
WHERE status != 'deleted'
GROUP BY CAST(backup_time AS DATE), folder_path
ORDER BY backup_date;
```

---

### 전체 Lakehouse 상태 대시보드 쿼리

모든 테이블을 한눈에 조회하는 요약 쿼리:

```sql
-- 모든 Iceberg 테이블의 레코드 수 + 최신 데이터 시각
SELECT 'entities' AS tbl, COUNT(*) AS rows, MAX(backup_time) AS latest
FROM polaris.netai.entities
UNION ALL
SELECT 'prim_snapshots', COUNT(*), MAX(backup_time)
FROM polaris.netai.prim_snapshots
UNION ALL
SELECT 'raw_backup_files', COUNT(*), MAX(backup_time)
FROM polaris.netai.raw_backup_files;
```

| tbl | rows | latest |
|-----|------|--------|
| entities | 18 | 2026-03-31 18:00:00 |
| prim_snapshots | 426 | 2026-03-31 18:00:00 |
| raw_backup_files | 1,340 | 2026-03-31 18:00:00 |

```sql
-- Iceberg 테이블 메타데이터 (파티션, 파일 수, 용량)
SELECT * FROM polaris.netai."entities$partitions";
SELECT * FROM polaris.netai."prim_snapshots$partitions";
SELECT * FROM polaris.netai."raw_backup_files$partitions";

-- Iceberg 스냅샷 이력 (테이블 변경 기록)
SELECT * FROM polaris.netai."entities$snapshots" ORDER BY committed_at DESC;
SELECT * FROM polaris.netai."raw_backup_files$snapshots" ORDER BY committed_at DESC;
```
