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
 │    (omniverse://10.38.38.32)    │                                  │
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
              │  - Congestion Map   │
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

## Two Backup Paths (Extension vs Pipeline)

```
   ┌─────────────────────────────┐     ┌─────────────────────────────┐
   │   Path A: Isaac Sim 내부     │     │  Path B: Nucleus Pipeline   │
   │   (Extension 기반)           │     │  (CLI 기반)                 │
   ├─────────────────────────────┤     ├─────────────────────────────┤
   │                             │     │                             │
   │  Isaac Sim 실행 중 필요      │     │  Isaac Sim 불필요           │
   │  실시간 인터랙티브           │     │  서버에서 자동화 가능        │
   │                             │     │                             │
   │  Stage.Traverse()           │     │  Nucleus에서 USD 다운로드    │
   │  → composed 전체 속성 추출   │     │  → override만 추출          │
   │  → Iceberg에 저장           │     │  → root.usda 생성           │
   │                             │     │  → Entity USD 다운로드       │
   │  backup_source: "extension" │     │  → MinIO + Iceberg 저장     │
   │                             │     │                             │
   │  복원: Stage 내에서          │     │  backup_source: "nucleus"   │
   │  Entity Reference 재설정    │     │  또는 "local"               │
   │  + Override 적용            │     │                             │
   │                             │     │  복원: MinIO에서 다운로드     │
   │                             │     │  → Isaac Sim에서 Open       │
   └─────────────────────────────┘     └─────────────────────────────┘
               │                                    │
               └──────────────┬─────────────────────┘
                              │
                              ▼
                 ┌───────────────────────┐
                 │    Iceberg Lakehouse  │
                 │                       │
                 │  - entities table     │
                 │  - prim_snapshots     │
                 │  - backup_source로    │
                 │    소스 구분          │
                 │  - SQL 타임트래블    │
                 └───────────────────────┘
```
