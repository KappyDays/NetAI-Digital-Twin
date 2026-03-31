# Nucleus Pipeline

Nucleus 서버 백업 CLI — Task 1 (Raw Backup)과 Task 2 (Entity Backup) 두 가지 모드를 지원합니다.

- **Task 1:** Nucleus 폴더 전체를 MinIO에 증분 백업하고 파일 메타데이터를 Iceberg에 기록합니다.
- **Task 2:** Isaac Sim 없이 PyUSD로 USD 파일을 파싱하여 Entity 경계(Reference/Payload)를 식별하고, 오버라이드된 Property만 추출하여 Lakehouse API에 전송합니다.

## 설치

### Local (Python 3.11 venv)

```bash
cd nucleus_pipeline
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Optional: Nucleus 서버 접속 (Python 3.10-3.12 필요)
pip install omniverseclient --extra-index-url https://pypi.nvidia.com
```

### Docker

```bash
docker build -t nucleus-pipeline .
```

## 사용법

### Task 1: Raw Backup (폴더 전체 백업)

Nucleus 서버의 특정 폴더를 통째로 MinIO에 업로드하고, 파일 메타데이터를 Iceberg에 기록합니다.

```bash
python main.py --raw-backup --nucleus-folder omniverse://10.38.38.48/Projects/MyScene --api-url http://localhost:8100
```

**동작:**
1. Nucleus 서버에서 지정 폴더의 모든 파일 목록 조회
2. 각 파일을 MinIO에 업로드
3. 파일 메타데이터(경로, 크기, 수정시간 등)를 Iceberg `raw_backup_files` 테이블에 기록

### Task 2: Entity Backup (USD Override 추출)

### 로컬 파일 처리

```bash
python main.py --local-path ../Omniverse/setup_stage.usda --api-url http://localhost:8100
```

### Nucleus 서버에서 다운로드

```bash
python main.py --nucleus-path omniverse://10.38.38.48/Projects/scene.usd --api-url http://localhost:8100
```

### Docker 실행

```bash
# 로컬 파일 (마운트)
docker run --rm -v $(pwd)/../Omniverse:/data nucleus-pipeline \
  --local-path /data/setup_stage.usda --api-url http://host.docker.internal:8100

# Nucleus 서버 (Linux, network_mode: host)
docker run --rm --network host nucleus-pipeline \
  --nucleus-path omniverse://10.38.38.48/Projects/scene.usd --api-url http://localhost:8100
```

## 출력 예시

```
============================================================
Nucleus Pipeline: USD → Iceberg Lakehouse
============================================================
Input: ../Omniverse/setup_stage.usda (local file)

Parsing USD file...
  Entities found: 6
  Prim snapshots: 6

  Entity summary:
    /World/Environment/Grid (Xform) — 1 override(s), hash=a1b2c3d4e5f6
    /World/Robots/Jetbot (Xform) — 1 override(s), hash=b2c3d4e5f6a7
    ...

Sending to Lakehouse API (http://localhost:8100)...

============================================================
Backup Complete
============================================================
  Status:           ok
  Entities inserted: 6
  Prims inserted:    6
  Backup source:     local
  Elapsed:           0.45s
============================================================
```

## CLI Arguments

| 인자 | 설명 | Task |
|------|------|------|
| `--raw-backup` | Raw Backup 모드 활성화 (Task 1) | Task 1 |
| `--nucleus-folder <URI>` | Raw Backup 대상 Nucleus 폴더 URI | Task 1 |
| `--nucleus-path <URI>` | Entity Backup 대상 Nucleus USD 파일 URI | Task 2 |
| `--local-path <PATH>` | Entity Backup 대상 로컬 USD 파일 경로 | Task 2 |
| `--api-url <URL>` | Lakehouse API 주소 (기본: `http://localhost:8100`) | 공통 |

## 아키텍처

### Task 1: Raw Backup

```
[Nucleus Server] --omni.client.list()--> [파일 목록 조회]
  --> [Iceberg raw_backup_files 조회] --> [증분 비교 (new/modified/deleted)]
  --> [omni.client.read_file()] --> [MinIO S3 업로드]
  --> [POST /api/v1/raw-backup/files] --> [Iceberg raw_backup_files 테이블]
```

### Task 2: Entity Backup

```
[Nucleus Server] --omni.client--> [Download] --temp file-->
[Local USD file] --PyUSD Stage.Open(LoadNone)--> [Entity ID: stage.Traverse()]
  --> [Override Extraction: Sdf.Layer API] --> [Hash + JSON]
  --> [POST /api/v1/entities/backup] --> [Iceberg entities + prim_snapshots 테이블]
```

핵심: Reference 내부 속성은 무시하고, root layer에 authored된 오버라이드만 추출합니다.
