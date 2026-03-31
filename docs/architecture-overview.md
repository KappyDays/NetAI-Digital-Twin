# BranDT Architecture Overview

## Full Pipeline: OpenUSD Stage → Lakehouse → Time Travel

```
 =====================================================================================
 |                          NVIDIA Omniverse Isaac Sim                                |
 |                                                                                     |
 |   ┌──────────────────────────────────────────────────────────┐                     |
 |   │                    USD Stage (Scene)                     │                     |
 |   │                                                          │                     |
 |   │   /World                                                 │                     |
 |   │   ├── /Environment (Xform)                               │                     |
 |   │   │   ├── /Grid      ◀── ref: grid.usd                  │                     |
 |   │   │   └── /Table     ◀── ref: table.usd                 │                     |
 |   │   ├── /Robots (Xform)                                    │                     |
 |   │   │   ├── /Jetbot    ◀── ref: jetbot.usd   ← 사용자가 이동 (Override) │       |
 |   │   │   └── /Kaya      ◀── ref: kaya.usd                  │                     |
 |   │   └── /Props (Xform)                                     │                     |
 |   │       ├── /Block_A   ◀── ref: basic_block.usd           │                     |
 |   │       └── /Block_B   ◀── ref: basic_block.usd           │                     |
 |   └──────────────────────────────────────────────────────────┘                     |
 |         │                                                          ▲               |
 |         │ File > Save                                              │ File > Open   |
 =========│==========================================================│================
           │                                                          │
           ▼                                                          │
 ┌─────────────────────────────────┐                                  │
 │    Omniverse Nucleus Server     │                                  │
 │    (omniverse://10.38.38.48)    │                                  │
 │                                 │                                  │
 │  /Projects/                     │                                  │
 │   └── scene.usd  ◀─ 최상위     │                                  │
 │  /Assets/                       │                                  │
 │   ├── jetbot.usd                │                                  │
 │   ├── kaya.usd                  │                                  │
 │   ├── table.usd                 │                                  │
 │   └── basic_block.usd          │                                  │
 └────────────┬────────────────────┘                                  │
              │                                                       │
              │ omniverseclient SDK                                   │
              │ (Python subprocess)                                   │
              ▼                                                       │
 ┌════════════════════════════════════════════════════════════════┐    │
 ║              Nucleus Pipeline  (nucleus_pipeline/)             ║    │
 ║                                                                ║    │
 ║  ┌──────────┐   ┌──────────────┐   ┌───────────────────────┐  ║    │
 ║  │ Download │   │  Parse USD   │   │  Generate root.usda   │  ║    │
 ║  │ scene.usd│──▶│  (PyUSD)     │──▶│  (경로 재작성)         │  ║    │
 ║  └──────────┘   │              │   │                       │  ║    │
 ║                 │ - Entity 식별│   │ omniverse://jetbot.usd│  ║    │
 ║                 │   (Ref/Pay)  │   │  → ./entities/jetbot  │  ║    │
 ║                 │ - Override   │   └───────────┬───────────┘  ║    │
 ║                 │   추출 (Sdf) │               │              ║    │
 ║                 │ - Asset URL  │               │              ║    │
 ║                 │   파싱       │               │              ║    │
 ║                 └──────┬───────┘               │              ║    │
 ║                        │                       │              ║    │
 ║                        ▼                       ▼              ║    │
 ║            ┌─────────────────────────────────────────┐        ║    │
 ║            │         Lakehouse API (:8100)            │        ║    │
 ║            │                                         │        ║    │
 ║            │  POST /entities/backup    POST /upload  │        ║    │
 ║            │  (Override + Metadata)    (USD files)   │        ║    │
 ║            └──────────┬──────────────────┬───────────┘        ║    │
 ║                       │                  │                    ║    │
 ╚═══════════════════════│══════════════════│════════════════════╝    │
                         │                  │                         │
              ┌──────────▼──────────┐  ┌────▼──────────────────┐     │
              │                     │  │                       │     │
              │    Apache Iceberg   │  │     MinIO (S3)        │     │
              │    (via Trino)      │  │                       │     │
              │                     │  │  backups/             │     │
              │  ┌───────────────┐  │  │  └── {timestamp}/     │     │
              │  │   entities    │  │  │      ├── root.usda ───┼─────┘
              │  │   table       │  │  │      └── entities/    │  다운로드 후
              │  ├───────────────┤  │  │          ├── jetbot   │  Isaac Sim에서
              │  │ entity_path   │  │  │          ├── kaya     │  Open → 복원
              │  │ entity_type   │  │  │          ├── table    │
              │  │ entity_hash   │  │  │          └── block    │
              │  │ backup_source │  │  │                       │
              │  │ backup_time   │  │  └───────────────────────┘
              │  └───────────────┘  │
              │                     │
              │  ┌───────────────┐  │
              │  │ prim_snapshots│  │
              │  │   table       │  │
              │  ├───────────────┤  │
              │  │ entity_path   │  │          ┌──────────────────────┐
              │  │ properties    │◀─┼── SQL ───│   Time Travel Query  │
              │  │ (Override     │  │          │                      │
              │  │  JSON)        │  │          │ "2시간 전 Jetbot의    │
              │  │ prim_hash     │  │          │  위치는 어디였지?"    │
              │  │ backup_time   │  │          │                      │
              │  └───────────────┘  │          │ SELECT properties    │
              │                     │          │ FROM prim_snapshots  │
              └─────────────────────┘          │ WHERE entity_path    │
                         ▲                     │ = '/World/.../Jetbot'│
                         │                     │ AND backup_time = ...│
                         │                     └──────────────────────┘
              ┌──────────┴──────────┐
              │  Web Dashboard      │
              │  (React :3000)      │
              │                     │
              │  - Entity Diff      │
              │    (3-Level 비교)    │
              │  - SQL Query        │
              │  - Raw Backup       │
              │    Explorer         │
              └─────────────────────┘
```

## Data Storage Strategy

```
                    ┌─────────────────────────────────────────┐
                    │          하나의 백업 시점 (T1)            │
                    ├─────────────────────────────────────────┤
                    │                                         │
                    │   MinIO (물리적 백업)                    │
                    │   ┌─────────────────────────────────┐   │
                    │   │ root.usda                       │   │
                    │   │  = Stage 전체 로컬 데이터        │   │
                    │   │  = 모든 Local Prim               │   │
                    │   │  + Reference/Payload 포인터      │   │
                    │   │  + Override (사용자 변경분)       │   │
                    │   ├─────────────────────────────────┤   │
                    │   │ entities/                        │   │
                    │   │  = 각 Entity의 원본 에셋 USD     │   │
                    │   │  (원본 파일명 기준, 중복 1회)     │   │
                    │   └─────────────────────────────────┘   │
                    │                                         │
                    │   Iceberg (논리적 백업)                  │
                    │   ┌─────────────────────────────────┐   │
                    │   │ entities table                   │   │
                    │   │  = Entity 메타데이터              │   │
                    │   │  (path, type, hash, source)      │   │
                    │   ├─────────────────────────────────┤   │
                    │   │ prim_snapshots table             │   │
                    │   │  = Override properties (JSON)    │   │
                    │   │  (사용자 변경분만, Entity별 개별) │   │
                    │   └─────────────────────────────────┘   │
                    │                                         │
                    ├─────────────────────────────────────────┤
                    │   복원 = root.usda + entities/*.usd     │
                    │          Isaac Sim이 합성 → composed    │
                    │                                         │
                    │   쿼리 = Iceberg SQL → Override 조회    │
                    └─────────────────────────────────────────┘
```

## Backup vs Restore Flow

```
   BACKUP (저장)                              RESTORE (복원)
   ──────────                                 ──────────────

   Nucleus Server                             MinIO Storage
       │                                          │
       │ omni.client                               │ GET /download-usd
       ▼                                          ▼
   ┌──────────┐                              ┌──────────┐
   │scene.usd │                              │root.usda │
   │(원본)    │                              │(재작성)  │
   └────┬─────┘                              └────┬─────┘
        │                                         │
        ▼                                         │    entities/
   ┌──────────┐    ┌──────────┐                   │    ├── jetbot.usd
   │  PyUSD   │    │root.usda │──▶ MinIO          │    ├── kaya.usd
   │  Parse   │──▶ │생성      │    upload         │    └── ...
   │          │    └──────────┘                    │
   │ Entity   │                                    ▼
   │ 식별     │    ┌──────────┐              ┌──────────────┐
   │ Override │    │Entity USD│──▶ MinIO     │  Isaac Sim   │
   │ 추출     │    │다운로드  │    upload     │  File > Open │
   │ URL 파싱 │    └──────────┘              │              │
   └────┬─────┘                              │ root.usda가  │
        │                                    │ entities/*.usd│
        ▼                                    │ 를 Reference로│
   ┌──────────┐                              │ 자동 로드     │
   │ Iceberg  │                              │              │
   │ INSERT   │    ◀──── SQL 쿼리 ──────────│ = 과거 시점의 │
   │          │         타임트래블           │   Stage 재현! │
   └──────────┘                              └──────────────┘
```

## Task 구성: Backup + Restore

```
   ┌──────────────────────────────────┐     ┌──────────────────────────────────────────┐
   │  Path A: Task 3                  │     │  Path B: Nucleus Pipeline (CLI 기반)     │
   │  Isaac Sim 내부 복원             │     │                                          │
   │  (KKR.TimeTravel Extension)      │     │  ┌──────────────────────────────────┐   │
   ├──────────────────────────────────┤     │  │  Task 1: Raw Backup              │   │
   │                                  │     │  ├──────────────────────────────────┤   │
   │  Isaac Sim 실행 중 사용          │     │  │  Nucleus 폴더 전체를 MinIO에      │   │
   │  Iceberg에서 백업 데이터 조회    │     │  │  증분 백업 + Iceberg 메타데이터  │   │
   │  Stage에 Override 적용           │     │  │  기록                            │   │
   │                                  │     │  │                                  │   │
   │  3가지 복원 모드:                │     │  │  python main.py --raw-backup     │   │
   │  - Changes Only (변경분만)       │     │  │    --nucleus-folder <URI>        │   │
   │  - Full Entity (Entity 전체)     │     │  │                                  │   │
   │  - Full All (전체 Stage)         │     │  │  → raw_backup_files 테이블       │   │
   │                                  │     │  └──────────────────────────────────┘   │
   │  Undo (메모리 스냅샷)            │     │                                          │
   │  + Nucleus Reopen 지원           │     │  ┌──────────────────────────────────┐   │
   │                                  │     │  │  Task 2: Entity Backup           │   │
   │  API URL 설정:                   │     │  ├──────────────────────────────────┤   │
   │  Local  localhost:8100           │     │  │  USD root layer override 추출    │   │
   │  Docker lakehouse-api:8000       │     │  │  → Iceberg (entities,            │   │
   │                                  │     │  │    prim_snapshots)               │   │
   │                                  │     │  │  + MinIO (USD 파일)              │   │
   │                                  │     │  │                                  │   │
   │                                  │     │  │  python main.py                  │   │
   │                                  │     │  │    --nucleus-path <URI>          │   │
   │                                  │     │  │                                  │   │
   │                                  │     │  │  → entities + prim_snapshots     │   │
   │                                  │     │  └──────────────────────────────────┘   │
   └──────────────────────────────────┘     └──────────────────────────────────────────┘
               │                                            │
               └────────────────────┬───────────────────────┘
                                    │
                                    ▼
                       ┌───────────────────────┐
                       │    Iceberg Lakehouse  │
                       │                       │
                       │  - entities table     │
                       │  - prim_snapshots     │
                       │  - raw_backup_files   │
                       │  - SQL 타임트래블     │
                       └───────────────────────┘
```
