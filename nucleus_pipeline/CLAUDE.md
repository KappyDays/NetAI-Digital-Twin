# Nucleus Pipeline — CLAUDE.md

## 모듈 개요

CLI 도구. Nucleus 서버에서 USD 파일을 백업하여 Iceberg Lakehouse에 저장.

- **Task 1 (Raw Backup):** `--raw-backup` — 폴더 단위 증분 백업 (modified_time + file_size 비교)
- **Task 2 (Entity Backup):** `--nucleus-path` — USD 파싱 → Entity/Prim override 추출 → Iceberg 저장

## Entity 경계 판별

- **Primary**: `Sdf.Layer` 순회 — Reference와 **Payload** arc 모두 감지
- **Supplementary**: `Usd.Stage.Open(root_layer)` 순회 — sublayer-only prim 보완 (NOT LoadNone)
- **LoadNone 사용 금지**: Payload prim을 `GetChildren()`에서 완전히 숨김
- **ListOp 완전 검사**: `_get_all_list_items()` — `prependedItems` + `appendedItems` + `explicitItems` 전부
- Reference/Payload arc → entity, `/World` 직속 자식 (arc 없음) → container
- 그 외 중간 Xform → entity 아님 (grouping용)
- Entity 경계에서 override 수집 중단 — 자식 entity의 override가 부모 hash에 오염되지 않음

## 설계 결정

- **subprocess DLL 분리:** `omni.client`와 PyUSD의 DLL 충돌 방지를 위해 nucleus_client.py는 subprocess로 실행
- **Deterministic ID:** `uuid5(NAMESPACE_URL, entity_path)` — 백업 간 동일 entity 추적

## `_to_json_value` 동기화

`usd_parser.py`와 `restore_engine.py`의 `_to_json_value()`는 **동일 입력에 동일 출력** 필수. 한쪽을 수정하면 반드시 다른 쪽도 동기화할 것 — hash 검증 불일치 방지.
