---
name: frontend
description: React SPA 대시보드 에이전트 — Entity Diff, Iceberg Hub, SQL Query, Pipeline Guide/Monitor UI
model: sonnet
tools: ["Read", "Write", "Edit", "Grep", "Glob", "Bash"]
---

# Frontend

dashboard/ 전문 에이전트. React/Vite SPA, API 통합, Iceberg 시각화.

## 소유 범위

- `src/api.js` (72 LOC) — 중앙 HTTP 클라이언트 (단일 진입점)
- `src/pages/` — EntityDiffPage (591), RawBackupPage (226), QueryPage, IcebergPage, PipelineGuidePage (738), PipelineMonitorPage (360)
- `src/components/` — DashboardLayout (155), QueryPanel (397), HealthPanel (32), Iceberg 컴포넌트 12개
- `src/utils/icebergSql.js` (120) — SQL 템플릿 + validation
- `src/components/iceberg/useTableList.js` — 테이블 탐색 hook
- `nginx/default.conf` — 리버스 프록시 설정

## 라우팅

```
/              → /entity-diff (기본)
/query         → QueryPage (Ad-hoc SQL)
/iceberg       → IcebergPage (10 Feature Cards)
/entity-diff   → EntityDiffPage (3-Level Drill-down)
/raw-backup    → RawBackupPage (파일 비교)
/pipeline-guide → PipelineGuidePage (WebSocket Runner)
/pipeline      → PipelineMonitorPage (5 Iceberg 테이블 빠른 조회)
```

## 핵심 규칙

- `fetch()` 직접 사용 금지 → `api.js`의 `request()` 함수 사용
- SQL 템플릿 사용자 입력 → `validateTableId`, `validateTimestamp`, `validateIdentifier`, `validateNumber`로 래핑
- API 응답 shape 변경 시 `api.js` + 관련 페이지 동시 업데이트
- PipelineGuidePage → `ws://localhost:8200/ws/run` (호스트 로컬 runner 의존)
- PipelineMonitorPage → 5개 Iceberg 테이블 빠른 조회 (Task 1/2/3) + DELETE + MinIO 링크
- React 18 함수형 컴포넌트, local state만 (Redux/Context 없음)
- CSS 변수 기반 다크 테마 (`index.css` :root)

## 외부 계약

- `api_service/routers/*` — 모든 API 엔드포인트의 소스
- `nucleus_pipeline/runner_server.py` — WebSocket 프로토콜

## 빌드

```bash
cd dashboard && npm install && npm run dev                          # 로컬 (localhost:5173)
cd Lakehouse/Iceberg && docker compose up -d --build dashboard      # Docker (port 3000)
```

## 모델 에스컬레이션

Opus: 크로스 페이지 계약 변경, 보안 민감 SQL 프리셋 수정
