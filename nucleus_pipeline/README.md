# Nucleus Pipeline

USD file → Entity extraction → Iceberg Lakehouse pipeline.

Isaac Sim 없이 PyUSD로 USD 파일을 파싱하여 Entity 경계(Reference/Payload)를 식별하고, 오버라이드된 Property만 추출하여 Lakehouse API에 전송합니다.

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

## 아키텍처

```
[Nucleus Server] --omni.client--> [Download] --temp file-->
[Local USD file] --PyUSD Stage.Open(LoadNone)--> [Entity ID: stage.Traverse()]
  --> [Override Extraction: Sdf.Layer API] --> [Hash + JSON]
  --> [POST /api/v1/entities/backup] --> [Iceberg Tables]
```

핵심: Reference 내부 속성은 무시하고, root layer에 authored된 오버라이드만 추출합니다.
