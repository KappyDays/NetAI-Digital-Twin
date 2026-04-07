# Nucleus Pipeline — CLAUDE.md

## Module Overview

CLI tool. Backs up USD files from the Nucleus server and stores them in the Iceberg Lakehouse.

- **Task 1 (Raw Backup):** `--raw-backup` — Folder-level incremental backup (modified_time + file_size comparison)
- **Task 2 (Entity Backup):** `--nucleus-path` — USD parsing → Entity/Prim override extraction → Iceberg storage

## Entity Boundary Detection

- **Primary**: `Sdf.Layer` traversal — Detects both Reference and **Payload** arcs
- **Supplementary**: `Usd.Stage.Open(root_layer)` traversal — Supplements sublayer-only prims (NOT LoadNone)
- **LoadNone prohibited**: Completely hides Payload prims from `GetChildren()`
- **Full ListOp inspection**: `_get_all_list_items()` — `prependedItems` + `appendedItems` + `explicitItems` all checked
- Reference/Payload arc → entity, `/World` direct children (no arc) → container
- Other intermediate Xforms → not entity (for grouping only)
- Override collection stops at Entity boundaries — prevents child entity overrides from contaminating parent hash

## Design Decisions

- **Subprocess DLL isolation:** `nucleus_client.py` runs as subprocess to prevent DLL conflicts between `omni.client` and PyUSD
- **Deterministic ID:** `uuid5(NAMESPACE_URL, entity_path)` — Tracks the same entity across backups

## `_to_json_value` Synchronization

`usd_parser.py`와 `restore_engine.py`의 `_to_json_value()`는 동일 출력 필수. 상세: root `CLAUDE.md` Key Conventions 참고.

## Cross-Module Sync Notes

- `usd_parser.py`와 `restore_engine.py`의 6개 공유 함수/상수는 동일 출력 필수 → root CLAUDE.md Key Conventions 참고
- Field-driven nested dict 전환으로 기존 Iceberg 데이터와 hash 호환 불가 — 재백업 필수

## ToDo
- [ ] Re-run Task 2 backup — field-driven nested dict 전환 후 기존 데이터와 hash 불일치. 새 백업 필수
