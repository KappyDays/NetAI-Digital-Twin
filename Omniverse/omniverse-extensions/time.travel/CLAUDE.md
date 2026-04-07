# KKR.TimeTravel Extension — CLAUDE.md

## Digital Twin Implementation 3 Stages

> Project-specific framework. A practical classification that compresses the lower 3 stages of the industry 5-stage model (Descriptive→Autonomous).
> The 3 stages can progress in parallel, not necessarily sequentially — this is an explanatory model, not an operational order.

| Stage | Description | Data Characteristics | Stage Capture Required? |
|-------|-------------|---------------------|------------------------|
| **Mirror** | Reflects the real world as-is in the virtual world (3D models, spatial layout, structures) | Static — USD file based | Yes (static snapshot) |
| **Observe** | Observes/reflects real-world real-time state in the virtual world (IoT sensors, state values) | Dynamic — IoT data stream | Conditional (see below) |
| **Modeling & Simulation** | Performs virtual simulation based on Mirror+Observe environment | Dynamic — simulation results | Yes (near-real-time capture) |

**Observe Stage capture decision criteria:**
- IoT pass-through (displaying values as-is on Stage) → Capture not needed (IoT originals are in Lakehouse)
- Derived state exists (IoT input → physics simulation → derived properties like transform/material) → Selective capture needed (derived state cannot be reproduced from IoT originals alone)

**KKR.TimeTravel 현재 위치: Mirror + M&S 구현 완료**
- Mirror: USD root layer override 추출 → Iceberg 저장 → 정적 시각 복원 (Task 2/3)
- M&S: 시뮬레이션 property 변경 캡처 → Iceberg 저장 → TimeSamples 베이킹 리플레이 (P0+P1 완료)

**미구현: Observe IoT 반영** — IoT source → Lakehouse → Extension 폴링 → Stage 반영 (P3)

## Module Overview

Isaac Sim 5.1.0 Extension. Backup restore (Task 3) + M&S Capture & Replay.

| File | Role |
|------|------|
| `extension.py` | Extension lifecycle, Timeline event subscription |
| `ui_builder.py` | UI: "Backup & Restore" (통합, one-click), Simulation Capture & Replay (Auto Capture, Scope, Session History, Bake, auto-play, replay guard) |
| `capture_coordinator.py` | 캡처 세션 오케스트레이터 — sequence_id, delta buffer, auto-flush |
| `physics_sampler.py` | PhysX step 콜백 — decimation, cached attr handle, dedup |
| `usd_change_watcher.py` | Tf.Notice 비물리 속성 — Timeline Gating, Path Blacklist, Authority |
| `property_authority_map.py` | prim+property 소유권 (physics vs usd_notice) |
| `entity_registry.py` | Stage scan, prim 분류(physics_driven/script_driven/static), Resync 증분 |
| `timeline_baker.py` | delta → Sdf.Layer timeSamples, sublayer insert/remove |
| `restore_engine.py` | Iceberg 백업에서 Stage 복원 + hash 검증 |
| `api_client.py` | stdlib urllib HTTP helpers (api_get, api_post_json) |

## Core Constraints

- **stdlib only** — no pip packages. Only `urllib`, `json`, `collections`, etc.
- `from pxr import ...` is available (Isaac Sim built-in PyUSD)
- Menu registration: under `Tools > KKR-Tools`

## Stage API Threading Rules

- All USD Stage-related calls (`pxr`, `omni.usd`) — must execute on the **main thread**
- `asyncio.ensure_future` + `async def` coroutine body = safe (main thread)
- Stage calls inside `loop.run_in_executor` = **prohibited** → silent app freeze (deadlock)
- Only network I/O (`api_get`) can be `await`ed in executor

## M&S Capture Constraints

- **PhysX 콜백 read-only**: `_on_physics_step` 내부에서 JSON 직렬화, 네트워크 호출, Stage traversal 금지. cached `attr.Get()`만 허용
- **JSON 직렬화 지연**: `add_delta()`는 `value_raw`(Python 원본)을 저장. `json.dumps`는 `flush_buffer()`에서만 실행 — PhysX 콜백 콜스택에서 절대 금지
- **Timeline Gating**: UsdChangeWatcher는 `is_playing() == True`일 때만 캡처 — 에디터 드래그 노이즈 차단
- **CaptureCoordinator가 유일한 버퍼 소유자**: PhysicsSampler/UsdChangeWatcher 모두 `coordinator.add_delta()` 호출 — 별도 버퍼 금지
- **Flush는 snapshot-and-swap**: `_buffer`를 빈 리스트로 교체 후 전송. 실패 시 snapshot을 원래 버퍼 앞에 복원. `_flush_in_flight` 가드로 동시 flush 방지
- **TimelineBaker anonymous layer**: `Sdf.Layer.CreateAnonymous("replay_bake.usda")`. 리플레이 제거 시 `remove_replay_layer()` 호출 — layer 객체 직접 삭제 금지

## Restore Behavior — Complete Restore

Single restore mode: completely reverts the Stage to the selected backup point.

**Process:**
1. Capture undo snapshot (saves current root layer state)
2. For each backup prim: remove extra overrides from root layer → apply backup data
3. Clean up Entity prims not in backup (remove from root layer)
4. Remove children under /World not in backup
5. Hash verification

## Property Application Rules During Restore

1. **Restore `specifier` via Sdf** — `prim_spec.specifier = _specifier_from_string(val)` (over/def/class). Included in hash.
2. **Set `typeName` via Sdf API** — `prim_spec.typeName = val` (Stage API cannot)
3. **Do not manually set `xformOpOrder`** — `UsdGeom.Xformable` manages it automatically
4. **Quaternion type matching** — Detect via `attr.GetTypeName()` (schema type, not current value). `quatf` → `Gf.Quatf`, otherwise → `Gf.Quatd`
5. **`Sdf.AssetPath` wrapping** — Check `isinstance(current, Sdf.AssetPath)` then wrap with `Sdf.AssetPath()`
6. **`meta:apiSchemas`** — Create `Sdf.TokenListOp` then use `prim_spec.SetInfo("apiSchemas", ...)` (Stage API cannot)
7. **`meta:variantSetNames`** — Set with `Sdf.StringListOp`
8. **`meta:variantSelection`** — Use `prim_spec.SetInfo("variantSelection", dict)`
9. **Missing attribute creation** — `_create_missing_attribute()` infers type then creates. Uses `PrimvarsAPI` for primvars.
10. **`unitsResolve` 필터** — `:unitsResolve` 접미사 속성은 metricsAssembler 자동생성. `_extract_layer_overrides()`에서 제외, `_clear_extra_overrides()`에서 보존, `xformOpOrder` 토큰에서 필터. `usd_parser.py`와 동기화 필수
11. **Arc 서브트리 보호** — `_cleanup_residual_prims`에서 Reference/Payload arc가 있는 prim과 그 자식 전체를 보호 (2-pass 알고리즘)
12. **`xformOp:opSuffix`** — 접미사 있는 xformOp (예: `scale:unitsResolve`)는 `AddXxxOp(opSuffix=suffix)` 전달 필수
13. **단일 축 회전** — `xformOp:rotateX/Y/Z`는 float scalar. `AddRotateXOp/YOp/ZOp()` 사용
14. **Attribute connection** — `conn:` 접두사 → `connectionPathList` Sdf API로 복원 (relationship의 `targetPathList`와 구분)
15. **Composition arc 복원** — 삭제된 entity prim 재생성 시 `_restore_composition_arc()`로 Reference/Payload arc 복원 필수
16. **`decl:` declared-only 속성** — 값/connection 없는 AttributeSpec을 `decl:{name}={typeName}` 형태로 캡처/보존. Shader `outputs:out` 등 shader network topology 유지에 필수. `usd_parser.py`와 동기화 필수
17. **Relationship metadata 복원** — `bindMaterialAs`, `customData` 등 property-level metadata는 `prop_spec.SetInfo(key, val)` via Sdf API. Material binding strength가 대표 사례
18. **Field-driven extraction** — `ListInfoKeys()` 전수 순회. 새 property type 자동 캡처. 미분류 key는 Tier 2 (audit)로 분류
19. **Nested dict format** — legacy flat prefix (`rel:`, `conn:`, `meta:`) 대신 `{typeName, specifier, meta, props, audit}` 구조. `_is_nested_format()` 감지
20. **Property-level metadata cleanup** — `_clear_extra_overrides()`에서 retained property의 extra metadata도 정리 (clearable_prop_meta set)

## Extraction Sync: 6 Shared Functions

`usd_parser.py`와 `restore_engine.py`는 아래 6개 함수/상수가 반드시 동일 출력:
- `TIER1_PRIM_KEYS`, `TIER2_PRIM_KEYS`, `TIER1_PROP_KEYS`, `TIER2_PROP_KEYS`
- `_serialize_list_op()`, `_serialize_field()`, `_to_json_value()`, `_compute_prim_hash()`
- `_extract_layer_overrides()` — field-driven `ListInfoKeys()` → nested dict

**데이터 포맷**: `{typeName, specifier, meta, props, audit}` nested dict
**Tier 1** (hash+restore): props + meta | **Tier 2** (audit): composition arcs, variability
**Legacy**: `_is_nested_format()` → `_apply_properties_legacy()` fallback for old flat data

## Session Progress (2026-04-02)

### Completed
- [x] Stage Restore rewrite — 3-mode → single Complete Restore. Fixed: apiSchemas, Quatf/Quatd, primvars:st, hash mismatch
- [x] _to_json_value TfToken fix — xformOpOrder character decomposition bug fixed (both usd_parser.py and restore_engine.py)
- [x] xformOp PrecisionDouble — ~~all AddXxxOp() PrecisionDouble~~ → schema-aware precision 감지로 개선 (2026-04-06)
- [x] Entity Restore removed — user did not request this feature
- [x] M&S Simulation capture demo — IoT sim + Tf.Notice capture + memory buffer
- [x] Lakehouse flush — POST /api/v1/realtime/flush + realtime_deltas table + snapshot-and-swap + auto-flush
- [x] Rate-limited Stage write — attr.Set() capped at 30Hz, capture at user-set rate (decoupled)
- [x] Backup Timeline UI — 2x3 button grid replacing << >> navigation
- [x] Nucleus file info display — Show File Info button
- [x] Code review fixes — async API calls (C1), restore confirmation gate reset (C2), json.loads protection (C3)
- [x] capture_time ISO format + value_json key alignment between Extension and API

### In Progress
- [x] ~~Hybrid time-travel strategy decision~~ — **결정 완료**: 궤적 캡처(M&S delta) + USD TimeSamples 베이킹 재생

### Architecture Decisions Resolved (2026-04-05 CCG 설계)
- [x] **리플레이 전략**: USD TimeSamples 베이킹 → Animation Timeline 네이티브 재생 (attr.Set() 루프 방식 기각)
- [x] **캡처 메커니즘**: Physics Callback (primary) + Tf.Notice (secondary) 하이브리드
- [x] **캡처 범위**: 3-Tier Scope (Auto Dynamic / Scoped / Full Stage)
- [x] **파이프라인 분리**: 4 Pipeline (PhysicsState, UsdChange, Sensor, Lifecycle) + Property Authority Map
- [x] **Tier 1 명칭**: "Physics Auto" → "Auto Dynamic" (물리 + 스크립트 시뮬레이션 모두 포함)

## ToDo — M&S Capture & Replay 구현

### P0: Critical — 완료 (2026-04-06)

- [x] **PhysX 구독 전환** — `physics_sampler.py` 구현. `subscribe_physics_step_events()` 사용
- [x] **CaptureCoordinator** — `capture_coordinator.py` 구현. 세션 라이프사이클, sequence_id, auto-flush
- [x] **sequence_id + sim_step** — thread-safe 단조증가 카운터 (`_sequence_lock`), `update_sim_step()` 연동
- [x] **Auto Capture 토글 UI** — `ui_builder.py` 구현. Timeline PLAY/STOP 이벤트 연동

### P1: Important — 완료 (2026-04-06)

- [x] **EntityRegistry** — `entity_registry.py` 구현. physics_driven/script_driven/static 분류, Resync 리스너
- [x] **PhysicsSampler** — `physics_sampler.py` 구현. decimation, cached handle, dedup
- [x] **UsdChangeWatcher** — `usd_change_watcher.py` 구현. Timeline Gating, Path Blacklist, Session Layer 제외
- [x] **PropertyAuthorityMap** — `property_authority_map.py` 구현. physics/usd_notice 소유권 판정
- [x] **TimelineBaker** — `timeline_baker.py` 구현. 청크 200 단위 async 베이킹, 취소 지원
- [x] **Capture Scope UI** — Auto Dynamic/Scoped/Full Stage 라디오 + Tracked Prims 표시
- [x] **Session History UI** — 세션 목록 + Bake to Timeline/Remove Replay 버튼

### P2: Enhancement

- [ ] **구조적 이벤트 캡처** — Prim 생성/삭제/재부모화를 `delta_type = 'prim_created' | 'prim_deleted'`로 기록. 새 Prim은 생성 시점 baseline snapshot 포함. `Tf.Notice.GetResyncedPaths()` 활용
- [ ] **디스크 fallback 버퍼** — Lakehouse 장애 시 extension 로컬 저장소에 JSON spool. 메모리 상한 (100K rows) 초과 시 oldest 삭제 + 경고. 세션 상태: `completed | partial | degraded`
- [x] **Flush 동시성 보호** — `_flush_in_flight` guard 구현 완료 (`capture_coordinator.py`)
- [ ] **Keyframe 시간 기반 트리거** — "매 N delta" → "매 T초 또는 매 M 물리 스텝" + 구조 변경 후 강제 Keyframe. 세션 시작 시 Initial Snapshot 필수
- [x] **Replay 모드 표시** — "REPLAY MODE ACTIVE" 라벨 + [Remove Replay] 버튼 구현 (`ui_builder.py`)
- [x] **Replay auto-play** — Bake 완료 후 Timeline 자동 재생 + 범위 자동 설정
- [x] **Replay guard** — replay 활성 시 Auto Capture 재트리거 방지
- [ ] **SensorCapture** — Camera/LiDAR blob → MinIO, 메타데이터 + URI만 Iceberg에 기록 (향후 확장)

### P3: Future

- [ ] Sub Layer override capture — Currently Root Layer only
- [ ] IoT data Observe reflection — Lakehouse polling → Stage 반영
- [ ] Learning Run 워크플로우 — 시뮬레이션 1회 실행 후 변경된 Prim 자동 수집 → Watchlist 생성 → 프리셋 저장
- [ ] Multi-session 비교 — 여러 시뮬레이션 세션을 동시 베이킹하여 비교 분석
- [ ] USD 파일 내보내기 — 베이킹된 replay sublayer를 .usdc 파일로 Export (Lakehouse 없이 공유 가능)

## Session Progress (2026-04-06 오후)

### Completed — Restore Engine
- [x] Composition arc 복원 — 삭제된 entity prim 재생성 시 Reference/Payload arc Sdf API로 복원
- [x] xformOp `opSuffix` 처리 — `xformOp:scale:unitsResolve` 등 접미사 op 정상 생성
- [x] Connection 캡처/복원 — `conn:` 접두사로 shader connection 직렬화 (connectionPathList)
- [x] Schema-aware precision — translate/orient/scale/rotatexyz 모든 xformOp에 적용
- [x] 단일 축 회전 핸들러 — `rotateX/Y/Z` AddRotateXOp/YOp/ZOp + scalar float
- [x] `all_warnings` 정의 위치 수정 — NameError 방지
- [x] `xformOpOrder` applied 카운트 수정 — prim_spec null 시 failed 처리
- [x] Hash 디버그 로깅 — verify_restore에서 mismatch 시 per-prim keys 출력

### Completed — Capture & Replay
- [x] 캡처 로깅 추가 — session start/stop/flush/prim register
- [x] `json.dumps` flush 시점 지연 — PhysX 콜백 안전 (value_raw → flush에서 직렬화)
- [x] Timeline 범위 자동 설정 — Bake 후 start/end/fps 자동 적용
- [x] Bake 후 자동 재생 — timeline.play() + 시간 0으로 리셋
- [x] Replay guard — is_replay_active 시 Auto Capture 재트리거 방지

### Completed — UI
- [x] Backup Timeline + Stage Restore → "Backup & Restore" 단일 섹션 통합
- [x] 더블클릭 확인 제거 → 원클릭 Restore
- [x] `_restore_confirmed` 미사용 잔재 제거

### Completed — 2026-04-06 Deep Dive (Q1+Q2)
- [x] Material Shader 보존 — `_cleanup_residual_prims` 2-pass: arc 서브트리(Reference/Payload) 전체 보호
- [x] Hash mismatch 해결 — `unitsResolve` 속성 + `xformOpOrder` 토큰 필터 (양 파일 동기화)
- [x] Session deltas=0 해결 — `stop_session()` race fix: sim_id/total_deltas 캡처 후 async 전달
- [x] flush_buffer sim_id race — batch_sim_id를 첫 delta에서 fallback 추출
- [x] Bake UnboundLocalError 해결 — `import omni.timeline` 모듈 레벨 이동 (timeline_baker, ui_builder, usd_change_watcher)
- [x] `_close_session_api` 불필요 import 정리 — `api_post_json_sync`, aliased `asyncio`/`json` 제거

### Completed — 2026-04-07 Deep Dive Round 2
- [x] unitsResolve disabled 방지 — xformOpOrder 재작성 시 Stage의 unitsResolve 토큰 병합 (base op 위치 뒤)
- [x] Material Shader 보존 (최종) — `decl:` prefix로 declared-only AttributeSpec 캡처 (Shader `outputs:out` 등)
- [x] connectionPathList appendedItems 지원 — 양 파일 동기화
- [x] Entity Backup Warning 억제 — stderr redirect 방식 (Tf.Diagnostic 대신)
- [x] session end_time null — `ended_at` → `end_time` field name 수정
- [x] Bake 프레임 정확도 — Stage timeCodesPerSecond 자동 감지 + t_max 기반
- [x] Session History UI — Nx2 그리드 + "deltas|frames" 표시 + _render_session_list_and_buttons 분리
- [x] stale session selection 방어 — reload 시 캐시에 없는 선택 ID 초기화

### Completed — 2026-04-07 Deep Dive Round 3
- [x] Q1-2: Restore 잔존 Prim 제거 — Step 2: arc 체크 → sublayer 존재 체크. `_cleanup_residual_prims`: prim spec 완전 제거. `verify_restore`: empty props 스킵
- [x] Q2-1: simulation_sessions 빈 컬럼 정리 — physics_config/capture_profile 제거, entity_count 실제 데이터 채움
- [x] Q2-2: Session 프레임 수 불일치 — `_estimate_frames` → `_format_session_info` (delta수+시간 표시, 가짜 frame 추정 제거)
- [x] Q2-5: Reset Replay — pre-bake timeline 상태 저장, `restore_timeline()` 메서드, "Reset Replay" 버튼
- [x] Hash composition 정렬 — usd_parser.py와 restore_engine.py 양쪽에서 empty props 스킵

### Completed — 2026-04-07 Deep Dive Round 4
- [x] Q1-2-1: unitsResolve 필터 완전 제거 — 양쪽 파일에서 skip/filter 4곳 제거, xformOpOrder merge 단순화, _clear_extra_overrides preserve 제거
- [x] Q2-1: Session 목록에 frame 추정치 추가 — `~{frames}f` 표시
- [x] Q2-2: Container::clear draw callback 에러 — next_update_async defer + rapid click 코일레싱
- [x] Q2-3: Reset Replay physics tensor warning — release_physics_objects() 선호출

### Completed — 2026-04-07 Field-Driven Capture 구현
- [x] Field-driven extraction — `ListInfoKeys()` 전수 순회, hand-picked → field-driven 전면 교체 (양쪽 파일)
- [x] Nested dict format — flat prefix (`rel:`, `conn:`, `meta:`) → `{typeName, specifier, meta, props, audit}` 구조
- [x] 2-Tier architecture — Tier 1 (hash+restore) / Tier 2 (audit only, composition arcs 등)
- [x] Material Strength 캡처/복원 — `bindMaterialAs` → `props.{rel}.metadata` + `rel_spec.SetInfo()`
- [x] Specifier 복원 — `prim_spec.specifier = _specifier_from_string(val)` via Sdf API
- [x] Type marshaller — `_serialize_field()` for ListOp, SdfPath, VtDictionary, ValueBlock, TfEnum
- [x] Legacy backward compat — `_is_nested_format()` → `_apply_properties_legacy()` 분기
- [x] Property metadata cleanup — `_clear_extra_overrides()`에서 retained property의 extra metadata 정리

### ToDo — 미해결
- [ ] **Re-run Task 2 backup (필수)** — field-driven nested dict 전환으로 기존 Iceberg 데이터와 hash 호환 불가. 새 백업 필수
- [ ] **Isaac Sim 런타임 테스트** — Material Strength 복원, specifier over/def, shader connections, hash 일치 검증
- [ ] **Dashboard EntityDiffPage 개선** — nested dict용 recursive diff viewer (현재 top-level key만 비교)
- [ ] Physics-free replay 상세 설계 (Q2-3) — Stage 복사본 생성 후 물리 관련 prim 제거, simulation replay. 추후 논의 필요
- [ ] simulation_sessions 테이블 재생성 — physics_config/capture_profile 컬럼 제거됨. 기존 테이블 DROP 필요
