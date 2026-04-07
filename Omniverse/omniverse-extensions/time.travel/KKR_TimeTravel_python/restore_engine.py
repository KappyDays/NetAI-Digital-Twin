"""Time Travel Restore Engine — Stage/Entity restore + Undo snapshot logic.

Handles:
- Undo snapshot capture (root layer overrides -> Python dict)
- Stage-wide restore (clear extras + apply backup + cleanup + verify)
- Entity-level restore
- Post-restore hash verification
"""

import hashlib
import json
from typing import Any

import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom


# ---------------------------------------------------------------------------
# Tier Classification Constants (synced with nucleus_pipeline/usd_parser.py)
# ---------------------------------------------------------------------------

# Tier 1: Hash + Restore fields (prim-level)
TIER1_PRIM_KEYS = {
    "typeName", "specifier", "kind", "instanceable", "active", "hidden",
    "customData", "assetInfo", "apiSchemas", "variantSelection",
    "documentation", "comment",
}

# Tier 2: Audit-only fields (prim-level) — excluded from hash
TIER2_PRIM_KEYS = {
    "references", "payload", "inherits", "specializes",
    "variantSetNames", "primOrder", "propertyOrder",
}

# Tier 1: Hash + Restore fields (property-level info keys)
TIER1_PROP_KEYS = {
    "default", "timeSamples", "typeName", "targetPaths", "connectionPaths",
    "custom", "bindMaterialAs", "customData", "colorSpace",
    "displayGroup", "displayName", "documentation", "allowedTokens",
    "comment", "hidden",
}

# Tier 2: Audit-only (property-level) — excluded from hash
TIER2_PROP_KEYS = {
    "variability",
}


# =====================================================================
#  Undo Snapshot — Capture current Stage root layer overrides
# =====================================================================

def capture_undo_snapshot() -> dict:
    """Capture current Stage root layer overrides as a Python dict.

    Returns:
        {prim_path: {prop_name: value, ...}, ...}
    """
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return {}
    root_layer = stage.GetRootLayer()
    if not root_layer or not root_layer.GetPrimAtPath("/World"):
        return {}
    snapshot = {}
    _collect_layer_overrides_recursive(root_layer, "/World", snapshot)
    return snapshot


def apply_undo_snapshot(snapshot: dict) -> tuple[int, int, list]:
    """Apply a previously captured undo snapshot to the current Stage."""
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return 0, 0, ["No active Stage"]

    applied = 0
    failed = 0
    warnings = []
    for prim_path, props in snapshot.items():
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            continue
        a, f, w = _apply_properties_to_prim(stage, prim, props)
        applied += a
        failed += f
        warnings.extend(w)
    return applied, failed, warnings


# =====================================================================
#  Layer Override Extraction (synced with usd_parser.py)
# =====================================================================

def _collect_layer_overrides_recursive(
    layer, prim_path: str, result: dict,
    entity_paths: set | None = None, _root_path: str | None = None,
):
    """Recursively collect all authored overrides from a Sdf layer.

    Args:
        entity_paths: if provided, children that are separate entities are
                      skipped (matches usd_parser.py boundary logic for hash).
        _root_path: the top-level entity path being collected (set on first call).
    """
    if _root_path is None:
        _root_path = prim_path

    prim_spec = layer.GetPrimAtPath(prim_path)
    if not prim_spec:
        return
    props = _extract_layer_overrides(prim_spec)
    # Always include — even empty props — so _cleanup_residual_prims won't strip this prim
    result[prim_path] = props
    for child_spec in prim_spec.nameChildren:
        child_path = f"{prim_path}/{child_spec.name}"
        # Skip children that are their own entity (prevents cross-entity hash contamination)
        if entity_paths is not None and child_path in entity_paths and child_path != _root_path:
            continue
        _collect_layer_overrides_recursive(layer, child_path, result, entity_paths, _root_path)


def _serialize_list_op(list_op) -> dict | None:
    """Serialize a USD ListOp to JSON dict, preserving structure."""
    result = {}
    for slot in ("explicitItems", "prependedItems", "appendedItems", "deletedItems", "orderedItems"):
        items = list(getattr(list_op, slot, []))
        if items:
            key = slot.replace("Items", "")
            result[key] = [str(i) for i in items]
    return result if result else None


def _serialize_field(val):
    """Generic Sdf field -> JSON-safe value. Handles ListOp, SdfPath, VtDictionary, etc."""
    if val is None:
        return None
    type_name = type(val).__name__
    # ListOp types
    if "ListOp" in type_name:
        return _serialize_list_op(val)
    # SdfPath
    if type_name == "Path":
        return str(val)
    # SdfReference / SdfPayload
    if type_name in ("Reference", "Payload"):
        result = {"assetPath": str(val.assetPath)}
        if val.primPath:
            result["primPath"] = str(val.primPath)
        return result
    # VtDictionary / dict -> recursive
    if isinstance(val, dict):
        return {str(k): _serialize_field(v) for k, v in val.items()}
    # SdfValueBlock
    if type_name == "ValueBlock":
        return {"_blocked": True}
    # TfEnum
    if type_name == "Enum":
        return str(val)
    # Specifier enum
    if type_name == "Specifier":
        specifier_map = {0: "def", 1: "over", 2: "class"}
        return specifier_map.get(val.value if hasattr(val, 'value') else int(val), str(val))
    # Fall back to existing _to_json_value
    return _to_json_value(val)


def _compute_prim_hash(props: dict) -> str:
    """Compute hash from Tier 1 fields only (exclude audit)."""
    hash_data = {k: v for k, v in props.items() if k != "audit"}
    props_json = json.dumps(hash_data, sort_keys=True, default=str)
    return hashlib.sha256(props_json.encode()).hexdigest()[:16]


def _extract_layer_overrides(layer_prim) -> dict:
    """Extract ALL authored overrides from Sdf.PrimSpec using field-driven approach.

    IMPORTANT: This function MUST stay in sync with
    nucleus_pipeline/usd_parser.py._extract_layer_overrides().
    Any changes here MUST be mirrored there for hash consistency.

    Produces nested dict with Tier 1 (hash+restore) and Tier 2 (audit) separation.

    Output structure:
        {
            "typeName": "Xform",
            "specifier": "over",
            "meta": {"kind": "component", ...},
            "props": {
                "xformOp:translate": {"value": [...], "type": "double3"},
                "material:binding": {"targets": {"explicit": [...]}, "type": "rel", "metadata": {...}}
            },
            "audit": {
                "prim": {"references": ..., "propertyOrder": ...},
                "props": {"xformOp:translate": {"variability": "Varying"}}
            }
        }
    """
    result = {}
    meta = {}
    audit_prim = {}

    # 1. Prim-level info keys — field-driven
    for key in layer_prim.ListInfoKeys():
        val = layer_prim.GetInfo(key)
        if val is None:
            continue
        serialized = _serialize_field(val)
        if serialized is None:
            continue

        if key == "typeName":
            result["typeName"] = serialized
        elif key == "specifier":
            result["specifier"] = serialized
        elif key in TIER1_PRIM_KEYS:
            meta[key] = serialized
        elif key in TIER2_PRIM_KEYS:
            audit_prim[key] = serialized
        else:
            # Unknown keys -> audit (future-proof)
            audit_prim[key] = serialized

    if meta:
        result["meta"] = meta

    # 2. Property-level — field-driven
    props = {}
    audit_props = {}

    for prop_spec in layer_prim.properties:
        prop_name = prop_spec.name
        prop_data = {}
        prop_audit = {}

        for info_key in prop_spec.ListInfoKeys():
            try:
                val = prop_spec.GetInfo(info_key)
            except Exception:
                continue  # Skip unsupported crate file types
            if val is None:
                continue
            serialized = _serialize_field(val)
            if serialized is None:
                continue

            if info_key == "default":
                prop_data["value"] = _to_json_value(val)  # Use existing precise serializer
            elif info_key == "timeSamples":
                prop_data["timeSamples"] = {str(k): _to_json_value(v) for k, v in val.items()}
            elif info_key == "typeName":
                prop_data["type"] = str(val)
            elif info_key == "targetPaths":
                prop_data["targets"] = _serialize_list_op(val) if hasattr(val, "explicitItems") else serialized
                prop_data["type"] = "rel"
            elif info_key == "connectionPaths":
                prop_data["connections"] = _serialize_list_op(val) if hasattr(val, "explicitItems") else serialized
            elif info_key == "custom":
                prop_data["custom"] = serialized
            elif info_key in TIER1_PROP_KEYS:
                # All other Tier 1 property metadata (bindMaterialAs, customData, etc.)
                prop_data.setdefault("metadata", {})[info_key] = serialized
            elif info_key in TIER2_PROP_KEYS:
                prop_audit[info_key] = serialized
            else:
                # Unknown property keys -> audit
                prop_audit[info_key] = serialized

        if prop_data:
            props[prop_name] = prop_data
        if prop_audit:
            audit_props[prop_name] = prop_audit

    if props:
        result["props"] = props

    # Build audit section
    audit = {}
    if audit_prim:
        audit["prim"] = audit_prim
    if audit_props:
        audit["props"] = audit_props
    if audit:
        result["audit"] = audit

    return result


def _to_json_value(val) -> Any:
    """Convert a USD/Sdf value to a JSON-serializable Python type.

    Must produce identical output to nucleus_pipeline/usd_parser.py._to_json_value().
    """
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        if val != val:  # NaN
            return "NaN"
        if val == float('inf'):
            return "Infinity"
        if val == float('-inf'):
            return "-Infinity"
        return round(val, 9)
    if isinstance(val, str):
        return val
    if type(val).__name__ == "AssetPath":
        return val.path
    # Quaternion types (Gf.Quatd, Gf.Quatf, Gf.Quath)
    if hasattr(val, "GetReal") and hasattr(val, "GetImaginary"):
        imag = val.GetImaginary()
        return [round(float(val.GetReal()), 9),
                round(float(imag[0]), 9),
                round(float(imag[1]), 9),
                round(float(imag[2]), 9)]
    if hasattr(val, "__len__"):
        result = []
        for v in val:
            # String-like types (str, TfToken) — keep as single string, not char array
            if isinstance(v, str) or type(v).__name__ in ("TfToken", "Token"):
                result.append(str(v))
            elif hasattr(v, "__len__"):
                try:
                    result.append([round(float(c), 9) for c in v])
                except (TypeError, ValueError):
                    result.append([str(c) for c in v])
            else:
                try:
                    result.append(round(float(v), 9))
                except (TypeError, ValueError):
                    result.append(str(v))
        return result
    return str(val)


# =====================================================================
#  Stage Restore — Complete restore to backup state
# =====================================================================

def restore_stage(
    entities: list[dict],
    prim_snapshots: list[dict],
    progress_callback=None,
) -> tuple[int, int, int, int, list]:
    """Restore entire Stage to exact backup state.

    Process:
      1. For each backed-up prim: clear extra root-layer overrides, apply backup
      2. Clean up residual prims inside entities (not in backup)
      3. Remove /World children not present in backup entities
      4. Verify hashes

    Returns:
        (entities_restored, props_applied, props_failed, prims_deleted, warnings)
    """
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return 0, 0, 0, 0, ["No active Stage"]
    root_layer = stage.GetRootLayer()
    if not root_layer:
        return 0, 0, 0, 0, ["No root layer"]

    # Build lookup structures
    all_warnings = []
    backup_prims = {}  # {full_prim_path: properties_dict}
    snaps_by_entity = {}
    for snap in prim_snapshots:
        ep = snap.get("entity_path", "")
        rel = snap.get("relative_path", "/")
        full = ep if rel == "/" else ep + rel
        props_str = snap.get("properties", "{}")
        try:
            props = json.loads(props_str) if isinstance(props_str, str) else props_str
        except (json.JSONDecodeError, TypeError):
            all_warnings.append(f"Invalid JSON for {full}, skipping")
            continue
        backup_prims[full] = props
        snaps_by_entity.setdefault(ep, []).append(snap)

    backup_entity_paths = {e["entity_path"] for e in entities}

    entities_restored = 0
    total_applied = 0
    total_failed = 0
    total_deleted = 0

    # -- Step 1: Apply backup overrides per entity -----------------------
    total = len(entities)
    for i, entity in enumerate(entities):
        ep = entity["entity_path"]
        if progress_callback:
            progress_callback(i + 1, total, ep)

        entity_prim_paths = sorted(
            p for p in backup_prims if p == ep or p.startswith(ep + "/")
        )

        for full_path in entity_prim_paths:
            # Clear properties/metadata on root layer that are NOT in backup
            _clear_extra_overrides(root_layer, full_path, backup_prims[full_path])

            # Get or create prim
            prim = stage.GetPrimAtPath(full_path)
            if not prim.IsValid():
                prim_type = backup_prims[full_path].get("typeName", "Xform")
                prim = stage.DefinePrim(full_path, prim_type)

                # Restore composition arc for entity root prim
                # (needed when prim was removed by a previous restore)
                if full_path == ep and prim.IsValid():
                    _restore_composition_arc(root_layer, full_path, entity)

            if not prim.IsValid():
                all_warnings.append(f"Cannot access prim: {full_path}")
                continue

            # Restore specifier from backup (nested format)
            backup_specifier = backup_prims[full_path].get("specifier")
            if backup_specifier:
                prim_spec = root_layer.GetPrimAtPath(full_path)
                if prim_spec:
                    try:
                        prim_spec.specifier = _specifier_from_string(backup_specifier)
                    except Exception:
                        pass  # Best-effort specifier restore

            a, f, w = _apply_properties_to_prim(stage, prim, backup_prims[full_path])
            total_applied += a
            total_failed += f
            all_warnings.extend(w)

        if entity_prim_paths:
            entities_restored += 1

        # Clean up child prims inside entity that are NOT in backup
        entity_snaps = snaps_by_entity.get(ep, [])
        backup_rel_paths = {s.get("relative_path", "/") for s in entity_snaps}
        backup_rel_paths.add("/")
        total_deleted += _cleanup_residual_prims(root_layer, ep, backup_rel_paths)

    # -- Step 2: Remove /World children not in backup entities -----------
    # Remove prims that exist ONLY in the root layer (not in any sublayer).
    # Sublayer-only prims (ground plane, lights, cameras, environment) are preserved.
    world_spec = root_layer.GetPrimAtPath("/World")
    if world_spec:
        # Cache sublayer references for sublayer-existence check
        sublayers = []
        for sl_path in root_layer.subLayerPaths:
            try:
                abs_path = root_layer.ComputeAbsolutePath(sl_path)
                sl = Sdf.Layer.Find(abs_path) or Sdf.Layer.Find(sl_path)
                if sl:
                    sublayers.append(sl)
            except Exception:
                pass

        children_to_remove = []
        for child_spec in world_spec.nameChildren:
            child_path = f"/World/{child_spec.name}"
            if child_path not in backup_entity_paths:
                # Check if prim exists in any sublayer — if so, preserve it
                exists_in_sublayer = any(
                    sl.GetPrimAtPath(child_path) for sl in sublayers
                )
                if not exists_in_sublayer:
                    children_to_remove.append(child_path)
        for child_path in children_to_remove:
            stage.RemovePrim(child_path)
            total_deleted += 1

    # -- Step 3: Post-restore hash verification --------------------------
    mismatches = verify_restore(stage, entities, snaps_by_entity)
    for m in mismatches:
        all_warnings.append(
            f"Hash mismatch: {m['entity_path']} "
            f"(expected={m['expected_hash']}, actual={m['actual_hash']})"
        )

    return entities_restored, total_applied, total_failed, total_deleted, all_warnings


def restore_single_entity(
    entity_path: str,
    prim_snapshots: list[dict],
) -> tuple[int, int, list]:
    """Restore a single entity from backup data."""
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return 0, 0, ["No active Stage"]
    return apply_entity_overrides(stage, entity_path, prim_snapshots)


def apply_entity_overrides(
    stage, entity_path: str, prim_snapshots: list[dict],
) -> tuple[int, int, list]:
    """Apply prim snapshot overrides to a single entity in the Stage."""
    total_applied = 0
    total_failed = 0
    warnings = []

    for snap in prim_snapshots:
        rel_path = snap.get("relative_path", "/")
        full_path = entity_path if rel_path == "/" else entity_path + rel_path

        prim = stage.GetPrimAtPath(full_path)
        if not prim.IsValid():
            prim_type = snap.get("prim_type", "Xform")
            prim = stage.DefinePrim(full_path, prim_type)
            if not prim.IsValid():
                warnings.append(f"Cannot create prim: {full_path}")
                continue

        props_str = snap.get("properties", "{}")
        try:
            props = json.loads(props_str) if isinstance(props_str, str) else props_str
        except (json.JSONDecodeError, TypeError):
            warnings.append(f"Invalid JSON for {full_path}")
            continue

        a, f, w = _apply_properties_to_prim(stage, prim, props)
        total_applied += a
        total_failed += f
        warnings.extend(w)

    return total_applied, total_failed, warnings


# =====================================================================
#  Root Layer Cleanup
# =====================================================================

def _restore_composition_arc(root_layer, prim_path: str, entity: dict):
    """Restore Reference or Payload composition arc on a newly created prim.

    When a prim was removed by a previous restore and needs to be re-created,
    DefinePrim alone only creates an empty prim. This function restores the
    composition arc so the original asset (mesh, materials, children) loads.

    Uses entity record's source_type and source_asset fields.
    """
    source_type = entity.get("source_type", "")
    source_asset = entity.get("source_asset", "")
    if not source_asset or source_type not in ("reference", "payload"):
        return

    prim_spec = root_layer.GetPrimAtPath(prim_path)
    if not prim_spec:
        return

    try:
        if source_type == "reference":
            ref = Sdf.Reference(source_asset)
            prim_spec.referenceList.explicitItems = [ref]
        elif source_type == "payload":
            pay = Sdf.Payload(source_asset)
            prim_spec.payloadList.explicitItems = [pay]
    except Exception:
        pass  # Best-effort arc restoration


def _clear_extra_overrides(root_layer, prim_path: str, backup_props: dict):
    """Remove property overrides and metadata from root layer NOT in backup.

    Ensures the prim matches backup state exactly — extra properties
    added after the backup point are cleared.

    Supports both legacy flat dict and new nested dict formats.
    """
    prim_spec = root_layer.GetPrimAtPath(prim_path)
    if not prim_spec:
        return

    # Build set of property names expected from backup
    if _is_nested_format(backup_props):
        # New format: property names are keys in backup_props["props"]
        backup_prop_names = set(backup_props.get("props", {}).keys())
    else:
        # Legacy format: extract property names from flat prefix keys
        backup_prop_names = set()
        for key in backup_props:
            if key.startswith("rel:"):
                backup_prop_names.add(key[4:])
            elif key.startswith("conn:"):
                backup_prop_names.add(key[5:])
            elif key.startswith("decl:"):
                backup_prop_names.add(key[5:])
            elif key.startswith("meta:") or key in ("typeName", "specifier"):
                continue
            else:
                backup_prop_names.add(key)

    # Remove properties not in backup.
    # Preserve properties with shader connections (structural, not removable).
    props_to_remove = []
    for p in prim_spec.properties:
        if p.name in backup_prop_names:
            continue
        # Preserve properties that have shader connections (connectionPathList)
        if isinstance(p, Sdf.AttributeSpec) and hasattr(p, "connectionPathList"):
            has_conn = False
            for slot in ("explicitItems", "prependedItems", "appendedItems"):
                if list(getattr(p.connectionPathList, slot, [])):
                    has_conn = True
                    break
            if has_conn:
                continue
        props_to_remove.append(p.name)
    for prop_name in props_to_remove:
        try:
            prim_spec.RemoveProperty(prim_spec.properties[prop_name])
        except Exception:
            pass  # Best-effort cleanup

    # Clear extra property-level metadata on retained properties (nested format only)
    if _is_nested_format(backup_props):
        backup_props_dict = backup_props.get("props", {})
        for p in prim_spec.properties:
            if p.name not in backup_prop_names:
                continue
            prop_backup = backup_props_dict.get(p.name, {})
            backup_meta = set(prop_backup.get("metadata", {}).keys())
            # Clear property info keys not in backup metadata
            clearable_prop_meta = {
                "bindMaterialAs", "customData", "colorSpace",
                "displayGroup", "displayName", "documentation",
                "allowedTokens", "comment", "hidden",
            }
            for mk in clearable_prop_meta:
                if mk not in backup_meta:
                    try:
                        if p.HasInfo(mk):
                            p.ClearInfo(mk)
                    except Exception:
                        pass

    # Clear metadata keys not in backup
    if _is_nested_format(backup_props):
        backup_meta_keys = set(backup_props.get("meta", {}).keys())
    else:
        backup_meta_keys = {k[5:] for k in backup_props if k.startswith("meta:")}
    clearable_meta = {
        "kind", "instanceable", "active", "hidden",
        "customData", "assetInfo", "apiSchemas",
        "variantSetNames", "variantSelection",
        "documentation", "comment",
    }
    current_keys = set(prim_spec.ListInfoKeys())
    for meta_key in clearable_meta:
        if meta_key in current_keys and meta_key not in backup_meta_keys:
            try:
                prim_spec.ClearInfo(meta_key)
            except Exception:
                pass


def _cleanup_residual_prims(
    root_layer, entity_path: str, backup_relative_paths: set,
) -> int:
    """Clear root layer overrides for prims inside an entity NOT in backup.

    Only affects root layer — prims from references/payloads are untouched.
    """
    entity_spec = root_layer.GetPrimAtPath(entity_path)
    if not entity_spec:
        return 0

    deleted = 0
    entity_path_len = len(entity_path)

    # Collect all descendant spec paths (deepest first for safe cleanup)
    all_paths = []
    _collect_spec_paths(root_layer, entity_path, all_paths)
    all_paths.sort(key=lambda p: -p.count("/"))

    # First pass: identify arc-bearing prims and their subtrees to protect
    arc_subtree_prefixes = set()
    for spec_path in all_paths:
        if spec_path == entity_path:
            continue
        prim_spec = root_layer.GetPrimAtPath(spec_path)
        if not prim_spec:
            continue
        has_arc = False
        for list_attr in ("referenceList", "payloadList"):
            lo = getattr(prim_spec, list_attr, None)
            if lo is None:
                continue
            for slot in ("prependedItems", "appendedItems", "explicitItems"):
                if list(getattr(lo, slot, [])):
                    has_arc = True
                    break
            if has_arc:
                break
        if has_arc:
            arc_subtree_prefixes.add(spec_path + "/")
            arc_subtree_prefixes.add(spec_path)  # protect the arc prim itself

    # Second pass: cleanup, skipping arc-bearing prims and their descendants
    for spec_path in all_paths:
        if spec_path == entity_path:
            continue
        # Skip if this path is an arc-bearing prim or a descendant of one
        if spec_path in arc_subtree_prefixes or any(
            spec_path.startswith(prefix) for prefix in arc_subtree_prefixes if prefix.endswith("/")
        ):
            continue
        rel_path = spec_path[entity_path_len:]
        if rel_path not in backup_relative_paths:
            prim_spec = root_layer.GetPrimAtPath(spec_path)
            if prim_spec:
                # Remove the entire prim spec from the layer (not just properties)
                parent_path = spec_path.rsplit("/", 1)[0] if "/" in spec_path else "/"
                parent_spec = root_layer.GetPrimAtPath(parent_path)
                if parent_spec:
                    try:
                        parent_spec.RemoveNameChild(prim_spec)
                    except Exception:
                        # Fallback: clear properties if spec removal fails
                        for prop_name in [p.name for p in prim_spec.properties]:
                            try:
                                prim_spec.RemoveProperty(prim_spec.properties[prop_name])
                            except Exception:
                                pass
                deleted += 1

    return deleted


def _collect_spec_paths(layer, parent_path: str, result: list):
    """Collect all descendant prim spec paths in a layer."""
    prim_spec = layer.GetPrimAtPath(parent_path)
    if not prim_spec:
        return
    for child in prim_spec.nameChildren:
        child_path = f"{parent_path}/{child.name}"
        result.append(child_path)
        _collect_spec_paths(layer, child_path, result)


# =====================================================================
#  Hash Verification
# =====================================================================

def verify_restore(stage, entities: list, prim_snapshots_by_entity: dict) -> list:
    """Verify that Stage overrides match backup hashes after restore.

    Uses _compute_prim_hash (Tier 1 only, audit excluded) for new nested format.
    Falls back to full-dict hash for legacy flat format.
    """
    mismatches = []
    root_layer = stage.GetRootLayer()
    if not root_layer:
        return mismatches

    # Build entity_paths set for boundary-aware collection (matches usd_parser.py)
    all_entity_paths = {e.get("entity_path", "") for e in entities if e.get("entity_path")}

    for entity in entities:
        ep = entity.get("entity_path", "")
        expected_hash = entity.get("entity_hash", "")
        if not ep or not expected_hash:
            continue

        current_overrides = {}
        _collect_layer_overrides_recursive(root_layer, ep, current_overrides,
                                           entity_paths=all_entity_paths)

        all_prim_hashes = []
        for prim_path, props in sorted(current_overrides.items()):
            if not props:
                continue  # Skip phantom empty specs (no properties)
            h = _compute_prim_hash(props)
            all_prim_hashes.append(h)

        actual_hash = hashlib.sha256(
            "".join(sorted(all_prim_hashes)).encode()
        ).hexdigest()[:16]

        if actual_hash != expected_hash:
            # Debug: log per-prim hash + JSON diff for diagnosis
            print(f"[RestoreVerify] {ep}: expected={expected_hash}, actual={actual_hash}")
            print(f"  Prim count: {len(current_overrides)}")
            # Compare with backup prim snapshots to find exact diff
            backup_snaps = prim_snapshots_by_entity.get(ep, [])
            backup_by_path = {}
            for s in backup_snaps:
                bp = ep + (s.get("relative_path", "/") if s.get("relative_path", "/") != "/" else "")
                try:
                    backup_by_path[bp] = json.loads(s.get("properties", "{}"))
                except Exception:
                    backup_by_path[bp] = {}
            for p, props in sorted(current_overrides.items()):
                ph = _compute_prim_hash(props)
                backup_props = backup_by_path.get(p, {})
                backup_ph = _compute_prim_hash(backup_props) if backup_props else "N/A"
                if ph != backup_ph:
                    # Show Tier 1 diff (audit excluded)
                    cur_t1 = json.dumps({k: v for k, v in props.items() if k != "audit"}, sort_keys=True, default=str)
                    bak_t1 = json.dumps({k: v for k, v in backup_props.items() if k != "audit"}, sort_keys=True, default=str)
                    print(f"  DIFF {p}: backup_hash={backup_ph}, actual_hash={ph}")
                    print(f"    backup: {bak_t1[:500]}")
                    print(f"    actual: {cur_t1[:500]}")
                else:
                    print(f"  OK   {p}: hash={ph}")
            mismatches.append({
                "entity_path": ep,
                "expected_hash": expected_hash,
                "actual_hash": actual_hash,
            })

    return mismatches


# =====================================================================
#  Property Application — Core override logic
# =====================================================================

def _is_nested_format(props: dict) -> bool:
    """Detect if properties use new nested dict format vs legacy flat format."""
    return "props" in props or "specifier" in props


def _specifier_from_string(s: str):
    """Convert specifier string to Sdf.Specifier enum."""
    mapping = {"def": Sdf.SpecifierDef, "over": Sdf.SpecifierOver, "class": Sdf.SpecifierClass}
    return mapping.get(s, Sdf.SpecifierOver)


def _apply_properties_to_prim(stage, prim, props: dict) -> tuple[int, int, list]:
    """Apply a dict of properties to a single USD prim.

    Detects format (legacy flat dict vs new nested dict) and delegates accordingly.
    """
    if not _is_nested_format(props):
        return _apply_properties_legacy(stage, prim, props)
    return _apply_properties_nested(stage, prim, props)


def _apply_properties_nested(stage, prim, props: dict) -> tuple[int, int, list]:
    """Apply nested dict format properties to a single USD prim.

    Handles:
    - specifier via Sdf API
    - typeName via Sdf API
    - meta dict (kind, instanceable, active, hidden, customData, assetInfo, apiSchemas, etc.)
    - props dict with value/type/targets/connections/timeSamples/metadata/custom
    """
    applied = 0
    failed = 0
    warnings = []
    root_layer = stage.GetRootLayer()
    prim_path = prim.GetPath()

    # 0. Set specifier via Sdf API
    backup_specifier = props.get("specifier")
    if backup_specifier:
        prim_spec = root_layer.GetPrimAtPath(prim_path)
        if prim_spec:
            try:
                prim_spec.specifier = _specifier_from_string(backup_specifier)
            except Exception as e:
                warnings.append(f"{prim_path}.specifier: {e}")

    # 1. Set typeName via Sdf layer (not settable via Stage API)
    type_name = props.get("typeName")
    if type_name:
        prim_spec = root_layer.GetPrimAtPath(prim_path)
        if prim_spec and prim_spec.typeName != type_name:
            prim_spec.typeName = type_name

    # 2. Apply prim metadata from meta dict
    #    Ensure prim spec exists in root layer before applying metadata
    #    (sub-prims like /World/Table/Surface may not have a spec yet)
    meta = props.get("meta", {})
    if meta:
        prim_spec = root_layer.GetPrimAtPath(prim_path)
        if not prim_spec:
            Sdf.CreatePrimInLayer(root_layer, prim_path)
    for meta_key, meta_val in meta.items():
        try:
            ok = _apply_metadata(stage, prim, meta_key, meta_val)
            if ok:
                applied += 1
            else:
                # Try direct Sdf SetInfo for keys not handled by _apply_metadata
                # (documentation, comment, etc.)
                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec:
                    prim_spec.SetInfo(meta_key, meta_val)
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim_path}.meta:{meta_key}: unknown metadata")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim_path}.meta:{meta_key}: {e}")

    # 3. Apply properties from props dict
    prop_dict = props.get("props", {})

    # Separate xformOps for batch handling
    xform_ops = {}
    xform_op_order_data = None

    for prop_name, prop_data in prop_dict.items():
        if prop_name == "xformOpOrder":
            xform_op_order_data = prop_data
        elif prop_name.startswith("xformOp:"):
            xform_ops[prop_name] = prop_data

    # 3a. Apply xformOps
    if xform_ops:
        xform_vals = {}
        xform_types = {}  # backup type hints for precision matching
        for op_name, op_data in xform_ops.items():
            if isinstance(op_data, dict):
                if "value" in op_data:
                    xform_vals[op_name] = op_data["value"]
                    if "type" in op_data:
                        xform_types[op_name] = op_data["type"]
                elif "timeSamples" in op_data:
                    # timeSamples for xformOps — apply via Sdf
                    try:
                        prim_spec = root_layer.GetPrimAtPath(prim_path)
                        if prim_spec:
                            attr_spec = prim_spec.attributes.get(op_name)
                            if attr_spec is None:
                                sdf_type = _sdf_type_from_string(op_data.get("type", "double3"))
                                attr_spec = Sdf.AttributeSpec(prim_spec, op_name, sdf_type)
                            ts = op_data["timeSamples"]
                            for t_str, t_val in ts.items():
                                attr_spec.SetInfo("timeSamples", {float(t_str): t_val})
                            applied += 1
                    except Exception as e:
                        failed += 1
                        warnings.append(f"{prim_path}.{op_name}: timeSamples error: {e}")
            else:
                xform_vals[op_name] = op_data

        if xform_vals:
            a, f, w = _apply_xform_ops(prim, xform_vals, xform_types)
            applied += a
            failed += f
            warnings.extend(w)

    # 3b. Re-author xformOpOrder explicitly via Sdf
    if xform_op_order_data is not None:
        order_val = xform_op_order_data.get("value") if isinstance(xform_op_order_data, dict) else xform_op_order_data
        if isinstance(order_val, list):
            try:
                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec:
                    current_order_attr = prim_spec.properties.get("xformOpOrder")
                    if current_order_attr is not None:
                        current_order_attr.default = list(order_val)
                    else:
                        attr_spec = Sdf.AttributeSpec(
                            prim_spec, "xformOpOrder",
                            Sdf.ValueTypeNames.TokenArray,
                        )
                        attr_spec.default = list(order_val)
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim_path}.xformOpOrder: prim_spec not found")
            except Exception as e:
                failed += 1
                warnings.append(f"{prim_path}.xformOpOrder: {e}")

    # 3c. Apply remaining properties (non-xformOp)
    for prop_name, prop_data in prop_dict.items():
        if prop_name.startswith("xformOp:") or prop_name == "xformOpOrder":
            continue  # Already handled above

        if not isinstance(prop_data, dict):
            # Unexpected format — skip
            warnings.append(f"{prim_path}.{prop_name}: unexpected prop_data format")
            continue

        prop_type = prop_data.get("type", "")

        try:
            # Relationships (material:binding, etc.)
            if "targets" in prop_data or prop_type == "rel":
                targets_data = prop_data.get("targets", {})
                # Extract target paths from ListOp structure
                target_paths = []
                if isinstance(targets_data, dict):
                    for slot in ("explicit", "prepended", "appended"):
                        target_paths.extend(targets_data.get(slot, []))
                elif isinstance(targets_data, list):
                    target_paths = targets_data

                rel = prim.GetRelationship(prop_name)
                if not rel.IsValid():
                    rel = prim.CreateRelationship(prop_name)
                if rel.IsValid() and target_paths:
                    rel.SetTargets([Sdf.Path(t) for t in target_paths])
                    applied += 1

                    # Apply relationship metadata (bindMaterialAs, etc.)
                    rel_metadata = prop_data.get("metadata", {})
                    if rel_metadata:
                        prim_spec = root_layer.GetPrimAtPath(prim_path)
                        if prim_spec:
                            rel_spec = prim_spec.relationships.get(prop_name)
                            if rel_spec:
                                for mk, mv in rel_metadata.items():
                                    try:
                                        rel_spec.SetInfo(mk, mv)
                                    except Exception as e2:
                                        warnings.append(f"{prim_path}.{prop_name}.meta:{mk}: {e2}")
                else:
                    failed += 1
                    warnings.append(f"{prim_path}.{prop_name}: rel invalid or no targets")

            # Connections (shader output connections like outputs:mdl:surface)
            elif "connections" in prop_data:
                conn_data = prop_data["connections"]
                conn_paths = []
                if isinstance(conn_data, dict):
                    for slot in ("explicit", "prepended", "appended"):
                        conn_paths.extend(conn_data.get(slot, []))
                elif isinstance(conn_data, list):
                    conn_paths = conn_data

                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec and conn_paths:
                    attr_spec = prim_spec.attributes.get(prop_name)
                    if attr_spec is None:
                        conn_type = _sdf_type_from_string(prop_type) if prop_type else Sdf.ValueTypeNames.Token
                        attr_spec = Sdf.AttributeSpec(prim_spec, prop_name, conn_type)
                    attr_spec.connectionPathList.explicitItems = [
                        Sdf.Path(c) for c in conn_paths
                    ]
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim_path}.{prop_name}: conn no prim_spec or paths")

            # TimeSamples (without value)
            elif "timeSamples" in prop_data and "value" not in prop_data:
                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec:
                    attr_spec = prim_spec.attributes.get(prop_name)
                    if attr_spec is None and prop_type:
                        sdf_type = _sdf_type_from_string(prop_type)
                        attr_spec = Sdf.AttributeSpec(prim_spec, prop_name, sdf_type)
                    if attr_spec:
                        ts = prop_data["timeSamples"]
                        ts_dict = {float(k): v for k, v in ts.items()}
                        attr_spec.SetInfo("timeSamples", ts_dict)
                        applied += 1
                    else:
                        failed += 1
                        warnings.append(f"{prim_path}.{prop_name}: cannot create attr for timeSamples")
                else:
                    failed += 1

            # Regular attribute with value
            elif "value" in prop_data:
                attr_val = prop_data["value"]
                attr = prim.GetAttribute(prop_name)
                if not attr.IsValid():
                    attr = _create_missing_attribute(prim, prop_name, attr_val)
                if attr and attr.IsValid():
                    _set_attr_value(attr, attr_val)
                    applied += 1
                else:
                    failed += 1
                    warnings.append(
                        f"{prim_path}.{prop_name}: attribute not found, "
                        f"cannot infer type to create"
                    )

            # Declared-only attribute (type but no value/connections/targets)
            elif prop_type and prop_type != "rel":
                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec:
                    attr_spec = prim_spec.attributes.get(prop_name)
                    if attr_spec is None:
                        sdf_type = _sdf_type_from_string(prop_type)
                        Sdf.AttributeSpec(prim_spec, prop_name, sdf_type)
                    applied += 1

            # Apply property-level metadata (custom, displayName, etc.)
            prop_metadata = prop_data.get("metadata", {})
            if prop_metadata and (prop_type != "rel"):
                # For non-relationship properties, apply metadata via Sdf
                prim_spec = root_layer.GetPrimAtPath(prim_path)
                if prim_spec:
                    prop_spec = prim_spec.properties.get(prop_name)
                    if prop_spec:
                        for mk, mv in prop_metadata.items():
                            try:
                                prop_spec.SetInfo(mk, mv)
                            except Exception as e2:
                                warnings.append(f"{prim_path}.{prop_name}.meta:{mk}: {e2}")

        except Exception as e:
            failed += 1
            warnings.append(f"{prim_path}.{prop_name}: {e}")

    return applied, failed, warnings


def _apply_properties_legacy(stage, prim, props: dict) -> tuple[int, int, list]:
    """Apply a legacy flat dict of properties to a single USD prim.

    Handles xformOps, relationships, metadata (including apiSchemas,
    variantSetNames, variantSelection), and regular attributes.
    Creates missing attributes when possible via type inference.
    """
    applied = 0
    failed = 0
    warnings = []

    root_layer = stage.GetRootLayer()

    # Classify properties
    xform_ops = {}
    relationships = {}
    connections = {}
    metadata = {}
    regular_attrs = {}
    declarations = {}  # declared-only attributes (type but no value)
    type_name = None

    xform_op_order = None  # captured for explicit re-authoring after xform ops

    for key, val in props.items():
        if key == "typeName":
            type_name = val
        elif key == "specifier":
            continue  # Sdf-only metadata, not settable via Stage API
        elif key == "xformOpOrder":
            xform_op_order = val
        elif key.startswith("xformOp:"):
            xform_ops[key] = val
        elif key.startswith("rel:"):
            relationships[key[4:]] = val
        elif key.startswith("conn:"):
            connections[key[5:]] = val
        elif key.startswith("decl:"):
            declarations[key[5:]] = val
        elif key.startswith("meta:"):
            metadata[key[5:]] = val
        else:
            regular_attrs[key] = val

    # 0. Set typeName via Sdf layer (not settable via Stage API)
    if type_name:
        prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
        if prim_spec and prim_spec.typeName != type_name:
            prim_spec.typeName = type_name

    # 1. Apply xformOps
    if xform_ops:
        a, f, w = _apply_xform_ops(prim, xform_ops)
        applied += a
        failed += f
        warnings.extend(w)

    # 1b. Re-author xformOpOrder explicitly via Sdf.
    # Backup now includes ALL tokens (including unitsResolve), so write directly.
    if xform_op_order is not None and isinstance(xform_op_order, list):
        try:
            prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
            if prim_spec:
                current_order_attr = prim_spec.properties.get("xformOpOrder")
                if current_order_attr is not None:
                    current_order_attr.default = list(xform_op_order)
                else:
                    attr_spec = Sdf.AttributeSpec(
                        prim_spec, "xformOpOrder",
                        Sdf.ValueTypeNames.TokenArray,
                    )
                    attr_spec.default = list(xform_op_order)
                applied += 1
            else:
                failed += 1
                warnings.append(f"{prim.GetPath()}.xformOpOrder: prim_spec not found")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.xformOpOrder: {e}")

    # 2. Apply relationships
    for rel_name, targets in relationships.items():
        try:
            rel = prim.GetRelationship(rel_name)
            if not rel.IsValid():
                rel = prim.CreateRelationship(rel_name)
            if rel.IsValid() and isinstance(targets, list):
                rel.SetTargets([Sdf.Path(t) for t in targets])
                applied += 1
            else:
                failed += 1
                warnings.append(f"{prim.GetPath()}.rel:{rel_name}: invalid")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.rel:{rel_name}: {e}")

    # 2b. Apply connections (Shader output connections like outputs:mdl:surface)
    for conn_name, conn_targets in connections.items():
        try:
            prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
            if prim_spec and isinstance(conn_targets, list):
                # Get or create the attribute spec for the connection
                attr_spec = prim_spec.attributes.get(conn_name)
                if attr_spec is None:
                    # Use declared type from decl: if available, else fall back to Token
                    conn_type = Sdf.ValueTypeNames.Token
                    decl_key = f"decl:{conn_name}"
                    if decl_key in props:
                        conn_type = _sdf_type_from_string(props[decl_key])
                    attr_spec = Sdf.AttributeSpec(
                        prim_spec, conn_name, conn_type)
                # Set connection paths
                attr_spec.connectionPathList.explicitItems = [
                    Sdf.Path(c) for c in conn_targets
                ]
                applied += 1
            else:
                failed += 1
                warnings.append(f"{prim.GetPath()}.conn:{conn_name}: no prim_spec")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.conn:{conn_name}: {e}")

    # 2c. Ensure declared-only attributes exist (e.g. Shader outputs:out)
    # These have a type but no value — they define shader network topology.
    for decl_name, decl_type_str in declarations.items():
        try:
            prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
            if prim_spec:
                attr_spec = prim_spec.attributes.get(decl_name)
                if attr_spec is None:
                    # Map common type strings to Sdf.ValueTypeNames
                    sdf_type = _sdf_type_from_string(decl_type_str)
                    Sdf.AttributeSpec(prim_spec, decl_name, sdf_type)
                applied += 1
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.decl:{decl_name}: {e}")

    # 3. Apply metadata
    for meta_key, meta_val in metadata.items():
        try:
            ok = _apply_metadata(stage, prim, meta_key, meta_val)
            if ok:
                applied += 1
            else:
                failed += 1
                warnings.append(f"{prim.GetPath()}.meta:{meta_key}: unknown metadata")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.meta:{meta_key}: {e}")

    # 4. Apply regular attributes
    for attr_name, attr_val in regular_attrs.items():
        try:
            attr = prim.GetAttribute(attr_name)
            if not attr.IsValid():
                # Attribute missing — try to create with inferred type
                attr = _create_missing_attribute(prim, attr_name, attr_val)
            if attr and attr.IsValid():
                _set_attr_value(attr, attr_val)
                applied += 1
            else:
                failed += 1
                warnings.append(
                    f"{prim.GetPath()}.{attr_name}: attribute not found, "
                    f"cannot infer type to create"
                )
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.{attr_name}: {e}")

    return applied, failed, warnings


def _apply_xform_ops(prim, xform_ops: dict, type_hints: dict | None = None) -> tuple[int, int, list]:
    """Apply xformOp properties to a prim.

    Args:
        type_hints: optional {op_name: type_str} from backup data for precision matching.
                    Used when composed attribute type differs from original root layer type.
    """
    applied = 0
    failed = 0
    warnings = []
    type_hints = type_hints or {}

    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        return 0, len(xform_ops), [f"{prim.GetPath()}: not Xformable"]

    existing_ops = {op.GetOpName(): op for op in xformable.GetOrderedXformOps()}

    def _precision_from_type(op_name, fallback_precision):
        """Determine precision: prefer backup type hint, then composed attr, then fallback."""
        hint = type_hints.get(op_name, "")
        if hint:
            h = hint.lower()
            if "float" in h and "double" not in h:
                return UsdGeom.XformOp.PrecisionFloat
            if "quatf" in h:
                return UsdGeom.XformOp.PrecisionFloat
            if "double" in h or "quatd" in h:
                return UsdGeom.XformOp.PrecisionDouble
        existing_attr = prim.GetAttribute(op_name)
        if existing_attr.IsValid():
            attr_type_str = str(existing_attr.GetTypeName()).lower()
            if "float" in attr_type_str and "double" not in attr_type_str:
                return UsdGeom.XformOp.PrecisionFloat
            if "quatf" in attr_type_str:
                return UsdGeom.XformOp.PrecisionFloat
        return fallback_precision

    for op_name, op_val in xform_ops.items():
        try:
            # Extract base operation type and suffix:
            # xformOp:rotateX:unitsResolve → type=rotateX, suffix=unitsResolve
            parts = op_name.split(":")
            short_name = parts[1].lower() if len(parts) >= 2 else parts[-1].lower()
            suffix = parts[2] if len(parts) >= 3 else ""

            if "translate" in short_name:
                add_precision = _precision_from_type(op_name, UsdGeom.XformOp.PrecisionDouble)
                xform_op = existing_ops.get(op_name) or xformable.AddTranslateOp(
                            precision=add_precision, opSuffix=suffix)
                if isinstance(op_val, list) and len(op_val) == 3:
                    actual_type = str(xform_op.GetAttr().GetTypeName()).lower()
                    if "float" in actual_type and "double" not in actual_type:
                        xform_op.Set(Gf.Vec3f(*[float(v) for v in op_val]))
                    else:
                        xform_op.Set(Gf.Vec3d(*op_val))
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: invalid translate value")

            elif "orient" in short_name:
                add_precision = _precision_from_type(op_name, UsdGeom.XformOp.PrecisionDouble)
                xform_op = existing_ops.get(op_name) or xformable.AddOrientOp(
                            precision=add_precision, opSuffix=suffix)
                if isinstance(op_val, list) and len(op_val) == 4:
                    # Detect precision from attribute TYPE NAME, not current value
                    attr_type = str(xform_op.GetAttr().GetTypeName()).lower()
                    if "quatf" in attr_type:
                        xform_op.Set(Gf.Quatf(
                            float(op_val[0]), float(op_val[1]),
                            float(op_val[2]), float(op_val[3]),
                        ))
                    else:
                        xform_op.Set(Gf.Quatd(
                            float(op_val[0]), float(op_val[1]),
                            float(op_val[2]), float(op_val[3]),
                        ))
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: invalid orient value")

            elif "rotatexyz" in short_name:
                add_precision = _precision_from_type(op_name, UsdGeom.XformOp.PrecisionDouble)
                xform_op = existing_ops.get(op_name) or xformable.AddRotateXYZOp(
                            precision=add_precision, opSuffix=suffix)
                if isinstance(op_val, list) and len(op_val) == 3:
                    actual_type = str(xform_op.GetAttr().GetTypeName()).lower()
                    if "double" in actual_type:
                        xform_op.Set(Gf.Vec3d(*[float(v) for v in op_val]))
                    else:
                        xform_op.Set(Gf.Vec3f(*[float(v) for v in op_val]))
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: invalid rotateXYZ value")

            elif short_name in ("rotatex", "rotatey", "rotatez"):
                add_precision = _precision_from_type(op_name, UsdGeom.XformOp.PrecisionDouble)
                add_fn = {"rotatex": xformable.AddRotateXOp,
                          "rotatey": xformable.AddRotateYOp,
                          "rotatez": xformable.AddRotateZOp}[short_name]
                xform_op = existing_ops.get(op_name) or add_fn(precision=add_precision, opSuffix=suffix)
                try:
                    xform_op.Set(float(op_val))
                    applied += 1
                except Exception as e:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: {e}")

            elif "scale" in short_name:
                add_precision = _precision_from_type(op_name, UsdGeom.XformOp.PrecisionDouble)
                xform_op = existing_ops.get(op_name) or xformable.AddScaleOp(
                            precision=add_precision, opSuffix=suffix)
                if isinstance(op_val, list) and len(op_val) == 3:
                    # Use type-matched Gf type — Vec3f for float3, Vec3d for double3
                    actual_type = str(xform_op.GetAttr().GetTypeName()).lower()
                    if "float" in actual_type and "double" not in actual_type:
                        xform_op.Set(Gf.Vec3f(*[float(v) for v in op_val]))
                    else:
                        xform_op.Set(Gf.Vec3d(*op_val))
                    applied += 1
                else:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: invalid scale value")

            else:
                # Generic xformOp (e.g. xformOp:transform)
                if op_name in existing_ops:
                    _set_attr_value(existing_ops[op_name].GetAttr(), op_val)
                    applied += 1
                else:
                    attr = prim.GetAttribute(op_name)
                    if attr.IsValid():
                        _set_attr_value(attr, op_val)
                        applied += 1
                    else:
                        failed += 1
                        warnings.append(f"{prim.GetPath()}.{op_name}: unknown xformOp")

        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.{op_name}: {e}")

    return applied, failed, warnings


def _sdf_type_from_string(type_str: str):
    """Map a Sdf type name string (e.g. 'token', 'float3') to Sdf.ValueTypeName."""
    _MAP = {
        "token": Sdf.ValueTypeNames.Token,
        "string": Sdf.ValueTypeNames.String,
        "bool": Sdf.ValueTypeNames.Bool,
        "int": Sdf.ValueTypeNames.Int,
        "float": Sdf.ValueTypeNames.Float,
        "double": Sdf.ValueTypeNames.Double,
        "float2": Sdf.ValueTypeNames.Float2,
        "float3": Sdf.ValueTypeNames.Float3,
        "float4": Sdf.ValueTypeNames.Float4,
        "double3": Sdf.ValueTypeNames.Double3,
        "color3f": Sdf.ValueTypeNames.Color3f,
        "color4f": Sdf.ValueTypeNames.Color4f,
        "asset": Sdf.ValueTypeNames.Asset,
        "texCoord2f[]": Sdf.ValueTypeNames.TexCoord2fArray,
        "normal3f[]": Sdf.ValueTypeNames.Normal3fArray,
    }
    return _MAP.get(type_str.lower().strip(), Sdf.ValueTypeNames.Token)


def _apply_metadata(stage, prim, meta_key: str, meta_val) -> bool:
    """Apply a single metadata key to a prim. Returns True on success."""
    root_layer = stage.GetRootLayer()

    if meta_key == "kind":
        Usd.ModelAPI(prim).SetKind(meta_val)
    elif meta_key == "instanceable":
        prim.SetInstanceable(bool(meta_val))
    elif meta_key == "active":
        prim.SetActive(bool(meta_val))
    elif meta_key == "hidden":
        prim.SetHidden(bool(meta_val))
    elif meta_key == "customData" and isinstance(meta_val, dict):
        for k, v in meta_val.items():
            prim.SetCustomDataByKey(k, v)
    elif meta_key == "assetInfo" and isinstance(meta_val, dict):
        for k, v in meta_val.items():
            prim.SetAssetInfoByKey(k, v)
    elif meta_key == "apiSchemas" and isinstance(meta_val, dict):
        prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
        if not prim_spec:
            return False
        list_op = Sdf.TokenListOp()
        if "prepend" in meta_val:
            list_op.prependedItems = meta_val["prepend"]
        if "delete" in meta_val:
            list_op.deletedItems = meta_val["delete"]
        if "append" in meta_val:
            list_op.appendedItems = meta_val["append"]
        if "explicit" in meta_val:
            list_op.explicitItems = meta_val["explicit"]
        prim_spec.SetInfo("apiSchemas", list_op)
    elif meta_key == "variantSetNames" and isinstance(meta_val, list):
        prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
        if not prim_spec:
            return False
        list_op = Sdf.StringListOp()
        list_op.prependedItems = meta_val
        prim_spec.SetInfo("variantSetNames", list_op)
    elif meta_key == "variantSelection" and isinstance(meta_val, dict):
        prim_spec = root_layer.GetPrimAtPath(prim.GetPath())
        if not prim_spec:
            return False
        prim_spec.SetInfo("variantSelection", meta_val)
    else:
        return False

    return True


# =====================================================================
#  Attribute Creation — Type inference for missing attributes
# =====================================================================

def _create_missing_attribute(prim, attr_name: str, value):
    """Create a missing attribute, inferring Sdf type from name and value.

    Returns the created UsdAttribute, or None if type cannot be inferred.
    """
    # Primvars: use PrimvarsAPI for correct type semantics
    if attr_name.startswith("primvars:"):
        pv_name = attr_name[len("primvars:"):]
        type_name = _infer_primvar_type(pv_name, value)
        if type_name:
            api = UsdGeom.PrimvarsAPI(prim)
            pv = api.CreatePrimvar(pv_name, type_name)
            if pv:
                return pv.GetAttr()
        return None

    # General attributes
    type_name = _infer_attr_type(attr_name, value)
    if type_name:
        return prim.CreateAttribute(attr_name, type_name)
    return None


def _infer_primvar_type(pv_name: str, value):
    """Infer Sdf type for a primvar from name and value."""
    # Well-known primvar types
    if pv_name in ("st", "st0", "st1", "st2"):
        if isinstance(value, list) and value and isinstance(value[0], list):
            return Sdf.ValueTypeNames.TexCoord2fArray
        return Sdf.ValueTypeNames.TexCoord2f
    if pv_name == "displayColor":
        if isinstance(value, list) and value and isinstance(value[0], list):
            return Sdf.ValueTypeNames.Color3fArray
        return Sdf.ValueTypeNames.Color3f
    if pv_name == "displayOpacity":
        if isinstance(value, list) and not (value and isinstance(value[0], list)):
            return Sdf.ValueTypeNames.FloatArray
        return Sdf.ValueTypeNames.Float
    # Fallback
    return _infer_attr_type(f"primvars:{pv_name}", value)


def _infer_attr_type(attr_name: str, value):
    """Infer Sdf type from attribute name and JSON value."""
    if isinstance(value, bool):
        return Sdf.ValueTypeNames.Bool
    if isinstance(value, int):
        return Sdf.ValueTypeNames.Int
    if isinstance(value, float):
        return Sdf.ValueTypeNames.Double
    if isinstance(value, str):
        token_attrs = {"visibility", "purpose", "orientation", "subdivisionScheme"}
        base_name = attr_name.split(":")[-1]
        return Sdf.ValueTypeNames.Token if base_name in token_attrs else Sdf.ValueTypeNames.String
    if isinstance(value, list):
        if not value:
            return None
        if isinstance(value[0], list):
            inner_len = len(value[0])
            return {
                2: Sdf.ValueTypeNames.Float2Array,
                3: Sdf.ValueTypeNames.Float3Array,
                4: Sdf.ValueTypeNames.Float4Array,
            }.get(inner_len)
        if all(isinstance(v, (int, float)) for v in value):
            n = len(value)
            return {
                2: Sdf.ValueTypeNames.Float2,
                3: Sdf.ValueTypeNames.Float3,
                4: Sdf.ValueTypeNames.Float4,
            }.get(n, Sdf.ValueTypeNames.FloatArray)
        if all(isinstance(v, str) for v in value):
            return Sdf.ValueTypeNames.StringArray
    return None


# =====================================================================
#  Value Helpers
# =====================================================================

def _parse_special_float(val):
    """Convert special float strings back to Python float values."""
    if isinstance(val, str):
        if val == "Infinity":
            return float('inf')
        if val == "-Infinity":
            return float('-inf')
        if val == "NaN":
            return float('nan')
    return val


def _is_numeric_type(attr) -> bool:
    """Check if a USD attribute's type is numeric."""
    type_name = str(attr.GetTypeName())
    numeric_keywords = ("float", "double", "half", "int", "uint", "long", "short")
    return any(k in type_name.lower() for k in numeric_keywords)


def _set_attr_value(attr, val):
    """Set a USD attribute value, converting Python types to USD types."""
    # Handle special float strings for numeric attributes
    if _is_numeric_type(attr):
        if isinstance(val, str):
            val = _parse_special_float(val)
        elif isinstance(val, list):
            val = [_parse_special_float(v) if isinstance(v, str) else v for v in val]

    # Check attribute type name for reliable type matching
    attr_type = str(attr.GetTypeName()).lower()

    # Matrix types (GfMatrix4d, GfMatrix3d, GfMatrix2d)
    if "matrix4d" in attr_type and isinstance(val, list) and len(val) == 4:
        attr.Set(Gf.Matrix4d(*[row for sublist in val for row in sublist]))
        return
    if "matrix3d" in attr_type and isinstance(val, list) and len(val) == 3:
        attr.Set(Gf.Matrix3d(*[row for sublist in val for row in sublist]))
        return
    if "matrix2d" in attr_type and isinstance(val, list) and len(val) == 2:
        attr.Set(Gf.Matrix2d(*[row for sublist in val for row in sublist]))
        return

    # AssetPath
    current = attr.Get()
    if isinstance(current, Sdf.AssetPath):
        path_str = str(val)
        if path_str.startswith("@") and path_str.endswith("@"):
            path_str = path_str[1:-1]
        attr.Set(Sdf.AssetPath(path_str))
        return

    # Quaternion — detect from type name, not current value (fixes Quatf/Quatd mismatch)
    if "quat" in attr_type and isinstance(val, list) and len(val) == 4:
        if "quatf" in attr_type:
            attr.Set(Gf.Quatf(float(val[0]), float(val[1]), float(val[2]), float(val[3])))
        else:
            attr.Set(Gf.Quatd(float(val[0]), float(val[1]), float(val[2]), float(val[3])))
        return

    # No current value — try direct set
    if current is None:
        attr.Set(val)
        return

    # List values — match to current value's Gf type
    if isinstance(val, list):
        if len(val) == 2:
            if isinstance(current, Gf.Vec2f):
                attr.Set(Gf.Vec2f(*val))
            elif isinstance(current, Gf.Vec2d):
                attr.Set(Gf.Vec2d(*val))
            else:
                attr.Set(val)
        elif len(val) == 3:
            if isinstance(current, Gf.Vec3d):
                attr.Set(Gf.Vec3d(*val))
            elif isinstance(current, Gf.Vec3f):
                attr.Set(Gf.Vec3f(*[float(v) for v in val]))
            elif isinstance(current, Gf.Vec3h):
                attr.Set(Gf.Vec3h(*[float(v) for v in val]))
            else:
                attr.Set(val)
        elif len(val) == 4:
            if isinstance(current, Gf.Vec4d):
                attr.Set(Gf.Vec4d(*val))
            elif isinstance(current, Gf.Vec4f):
                attr.Set(Gf.Vec4f(*[float(v) for v in val]))
            else:
                attr.Set(val)
        else:
            attr.Set(val)
    elif isinstance(val, bool):
        attr.Set(val)
    elif isinstance(val, (int, float)):
        if isinstance(current, float):
            attr.Set(float(val))
        elif isinstance(current, int):
            attr.Set(int(val))
        else:
            attr.Set(val)
    elif isinstance(val, str):
        attr.Set(val)
    else:
        attr.Set(val)
