# Dashboard — CLAUDE.md

## Module Overview

React SPA (Vite). Provides Entity Diff, Raw Backup, Iceberg Hub, Pipeline Guide/Monitor, and SQL Query interfaces. nginx reverse proxy (port 3000).

## Active Pages

| Route | Component | Purpose |
|-------|-----------|---------|
| `/` | → `/entity-diff` | 기본 리다이렉트 |
| `/query` | `QueryPage` | Trino SQL execution + Iceberg Hub |
| `/iceberg` | `IcebergPage` | Iceberg table exploration (Time Travel, Snapshots, etc.) |
| `/entity-diff` | `EntityDiffPage` | Entity 3-Level Drill-down Diff |
| `/raw-backup` | `RawBackupPage` | Raw Backup file comparison |
| `/pipeline-guide` | `PipelineGuidePage` | Nucleus Pipeline 커맨드 가이드 + 실행 |
| `/pipeline` | `PipelineMonitorPage` | 5개 Iceberg 테이블 빠른 조회 (Task 1/2/3) + Delete + MinIO 링크 |

## Pipeline Guide (`src/pages/PipelineGuidePage.jsx`)

커맨드 템플릿에 `{placeholder}` 토큰을 사용하며, **Fill 버튼**으로 파라미터 입력 패널을 열 수 있다.

- `COMMANDS` 배열 — 각 item에 `cmd` (토큰 포함 템플릿)와 `placeholders` (키 → `{ label, default }`) 정의
- `CommandBlock` — `placeholders` prop을 받아 Fill 패널 표시 여부 결정; 값 변경 시 resolved 커맨드 자동 갱신
- Fill 패널은 `{key}` 토큰을 실제 값으로 치환해 Run/Copy에 반영
- 커맨드를 직접 수정(클릭 → textarea)하면 Fill 패널과 독립적으로 편집 가능
- Runner WebSocket (`ws://{url}/ws/run`) — Pipeline Runner 서버(`runner_server.py`)에 연결해 명령 실행 및 스트리밍 출력

## Key Rules

### API Calls
- All API calls must use the centralized functions in `api.js` (`request()` based)
- Do not use `fetch()` directly — ensures error handling and base URL consistency
- Entity/RawBackup specific functions: `getEntityBackupTimes()`, `getEntityDiff()`, `getPrimDiff()`, `getRawBackupTimes()`, `getRawBackupDiff()`, etc.

### SQL Templates (`utils/icebergSql.js`)
- All user inputs must be **wrapped with validation functions**:
  - `validateTableId(table)` — `^[a-zA-Z_][a-zA-Z0-9_."]*$`
  - `validateTimestamp(ts)` — ISO 8601 format
  - `validateIdentifier(name)` — `^[a-zA-Z_][a-zA-Z0-9_]*$`
  - `validateNumber(val)` — `Number.isFinite()`
- Do not directly insert into SQL via string interpolation

### Iceberg catalog name
- Both Dashboard SQL and API/Pipeline code use `polaris` as the Trino catalog name
- Trino catalog config: `Lakehouse/Iceberg/trino/catalog/polaris.properties` → catalog name = `polaris`
- All SQL queries must use `polaris.netai.*` (e.g. `SELECT * FROM polaris.netai.entities`)

### Performance
- `useTableList.js` uses `Promise.all()` for parallel execution (no N+1 sequential execution)

## Build

```bash
# Local development
cd dashboard && npm install && npm run dev

# Docker (nginx serving)
cd Lakehouse/Iceberg && docker compose up -d --build dashboard
```
