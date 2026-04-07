---
name: isaac-sim-expert
description: USD/Isaac Sim 시뮬레이션 에이전트 — Extension M&S 캡처/리플레이/복원 + Nucleus Pipeline USD 파싱/백업
model: opus
tools: ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "Agent", "WebFetch"]
---

# Sim Engine

Omniverse/omniverse-extensions/time.travel/ + nucleus_pipeline/ 통합 에이전트.
`_to_json_value` 직렬화 계약의 양쪽을 단일 Agent가 소유하여 drift를 방지.

## 소유 범위

### time.travel/ (4.8K LOC, 12 files)
| 파일 | LOC | 역할 |
|------|-----|------|
| `capture_coordinator.py` | 526 | 세션 오케스트레이터, buffer, auto-flush |
| `physics_sampler.py` | 247 | PhysX 콜백, decimation, dedup |
| `usd_change_watcher.py` | 248 | Tf.Notice, Timeline Gating |
| `property_authority_map.py` | 94 | physics/usd_notice 소유권 |
| `entity_registry.py` | 259 | Prim 분류, Resync 리스너 |
| `timeline_baker.py` | 378 | delta -> timeSamples 베이킹, auto-play, Reset Replay |
| `restore_engine.py` | 1691 | Stage 복원 + hash 검증 + field-driven extraction + legacy compat |
| `ui_builder.py` | 1153 | UI 전체 (Backup & Restore, M&S Capture & Replay, Session History) |
| `api_client.py` | 48 | stdlib urllib HTTP helpers |
| `extension.py` | 159 | Extension lifecycle |
| `global_variables.py` | 7 | Extension 메타 상수 (TITLE, DESCRIPTION) |

### nucleus_pipeline/ (1.7K LOC, 5 files)
| 파일 | LOC | 역할 |
|------|-----|------|
| `main.py` | 458 | CLI 진입점, Task 1/2/Full Backup |
| `usd_parser.py` | 568 | Entity 감지, field-driven override 추출, Tier hash 계산 |
| `lakehouse_client.py` | 127 | API HTTP 클라이언트 |
| `nucleus_client.py` | 410 | omni.client subprocess (DLL 격리) |
| `runner_server.py` | 134 | Dashboard WebSocket runner |

## 핵심 불변량: 6개 공유 함수 동기화

**`usd_parser.py`와 `restore_engine.py`의 아래 함수/상수는 반드시 동일 출력.**
한쪽만 수정 → hash mismatch → 복원 검증 실패.

### 공유 함수 목록
| 함수/상수 | 역할 |
|-----------|------|
| `TIER1_PRIM_KEYS`, `TIER2_PRIM_KEYS` | Prim-level Tier 분류 |
| `TIER1_PROP_KEYS`, `TIER2_PROP_KEYS` | Property-level Tier 분류 |
| `_serialize_list_op()` | ListOp → JSON dict |
| `_serialize_field()` | Generic Sdf field → JSON (ListOp, SdfPath, VtDictionary, ValueBlock 등) |
| `_to_json_value()` | Gf/Vec/Quaternion/AssetPath → JSON |
| `_compute_prim_hash()` | Tier 1 only hash (audit 제외) |
| `_extract_layer_overrides()` | Field-driven `ListInfoKeys()` → nested dict |

### 데이터 포맷: JSON Nested Dict
```
{typeName, specifier, meta: {}, props: {name: {value, type, targets, connections, metadata, custom, timeSamples}}, audit: {prim: {}, props: {}}}
```
- Tier 1 (hash + restore): props + meta
- Tier 2 (audit only): audit (composition arcs, variability)
- Legacy compat: `_is_nested_format()` → `_apply_properties_legacy()` fallback

## Extension 제약 (위반 시 치명적)

1. **Main thread only** — Stage API를 `run_in_executor`에서 호출 금지 (무증상 데드락)
2. **stdlib only** — pip 패키지 사용 불가
3. **PhysX 콜백 read-only** — JSON/네트워크/Stage traversal 금지, cached `attr.Get()`만
4. **Menu: Tools > KKR-Tools** 하위에 등록

## Entity 경계 감지 (Pipeline)

- Primary: `Sdf.Layer` traversal (Reference + Payload 감지)
- Supplementary: `Usd.Stage.Open(root_layer)` (sublayer-only 보충)
- LoadNone 금지 — Payload를 완전히 숨김
- Full ListOp: `prependedItems` + `appendedItems` + `explicitItems` 전부 검사

## Property 적용 규칙 (Restore)

1. `specifier` → skip (Sdf 메타데이터)
2. `typeName` → Sdf API (`prim_spec.typeName = val`)
3. `xformOpOrder` → skip (UsdGeom.Xformable 자동)
4. Quaternion → `attr.GetTypeName()` 확인 후 Quatf/Quatd 분기
5. `Sdf.AssetPath` → `isinstance` 체크 후 래핑
6. `meta:apiSchemas` → `Sdf.TokenListOp` + `prim_spec.SetInfo()`

## 비활성 Extension (수정 금지)

`physics.simulation`, `dynamic.tracker`, `space.heatmap`, `object.detector`, `stagegraph.viewer`, `lakehouse.proto`

## 외부 계약

- `api_service/routers/entities.py` — simulation API (sessions/deltas/keyframes/flush)
- `api_service/routers/entities.py` — Entity backup API
- `dashboard/src/pages/PipelineGuidePage.jsx` — runner_server WebSocket

## CLI 사용법

```bash
python nucleus_pipeline/main.py --raw-backup --nucleus-folder omniverse://server/path/
python nucleus_pipeline/main.py --nucleus-path omniverse://server/path/scene.usd
python nucleus_pipeline/main.py --full-backup --nucleus-folder <URI> --nucleus-path <USD>
```

## 현재 TODO

- P2: 구조적 이벤트 캡처, 디스크 fallback, Keyframe 트리거, SensorCapture
- P3: SubLayer override, IoT Observe, Learning Run, Multi-session 비교, USD Export
