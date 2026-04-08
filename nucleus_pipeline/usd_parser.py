"""USD file parser — extracts Entity boundaries and property overrides using PyUSD.

Hybrid approach:
  1. Usd.Stage.Traverse() for Entity identification (Reference/Payload detection)
  2. Sdf.Layer API for override-only property extraction (root layer authored specs)

This avoids loading Reference content (no network access needed) while correctly
identifying all Entity boundaries in the composed stage hierarchy.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Tier Classification Constants
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


def parse_usd(file_path: str) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Parse a USD file and extract Entity records + Prim Snapshot records + asset URLs.

    Args:
        file_path: Path to local .usd/.usda file

    Returns:
        (entities, prim_snapshots, asset_urls)
        - entities: list of dicts matching EntityRecord schema
        - prim_snapshots: list of dicts matching PrimSnapshotRecord schema
        - asset_urls: {entity_path: original_reference_or_payload_url}
    """
    import os
    import sys

    from pxr import Sdf

    # Suppress USD C++ composition warnings (metricsAssembler sublayer, missing payloads).
    # nucleus_pipeline runs outside Isaac Sim, so these asset paths are unresolvable.
    # os.dup2 redirects OS-level fd 2 (C++ TF_WARN writes directly to fd 2,
    # bypassing Python's sys.stderr).
    _old_fd = os.dup(2)
    _devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull, 2)
    try:
        root_layer = Sdf.Layer.FindOrOpen(file_path)
    finally:
        os.dup2(_old_fd, 2)
        os.close(_old_fd)
        os.close(_devnull)
    if not root_layer:
        raise RuntimeError(f"Failed to open USD layer: {file_path}")

    # Step 1: Identify entities
    # Primary: Sdf.Layer traversal — reliable for root layer content,
    # correctly detects both references AND payloads (LoadNone hides payloads).
    entity_paths = {}
    _traverse_layer_for_entities(root_layer, "/World", entity_paths)

    # Supplementary: Stage traversal for sublayer prims not in root layer.
    # Uses LoadNone to suppress payload/sublayer load warnings — nucleus_pipeline
    # runs outside Isaac Sim, so asset paths (Payload, metricsAssembler) are unresolvable.
    if root_layer.subLayerPaths:
        try:
            from pxr import Usd
            # Suppress C++ TF_WARN via OS fd 2 redirect (same as above)
            _old_fd2 = os.dup(2)
            _devnull2 = os.open(os.devnull, os.O_WRONLY)
            os.dup2(_devnull2, 2)
            try:
                stage = Usd.Stage.Open(root_layer, load=Usd.Stage.LoadNone)
            finally:
                os.dup2(_old_fd2, 2)
                os.close(_old_fd2)
                os.close(_devnull2)
            stage_paths = {}
            _traverse_stage_for_entities(stage, "/World", stage_paths)
            for ep, info in stage_paths.items():
                if ep not in entity_paths:
                    entity_paths[ep] = info
        except Exception:
            pass

    # Step 2: Extract overrides from root layer (Sdf API)
    entities = []
    prim_snapshots = []
    asset_urls = {}  # {entity_path: original_url}

    for entity_path, info in entity_paths.items():
        # Include ALL entity asset URLs regardless of protocol (https://, omniverse://)
        if info["source_asset"]:
            asset_urls[entity_path] = info["source_asset"]

        # Collect overrides for this entity and its children from root layer
        # Pass entity_paths so nested entity boundaries are not crossed
        entity_overrides = _collect_overrides_recursive(root_layer, entity_path, entity_paths)

        # Compute combined hash from all sub-prim overrides
        # Skip empty props (phantom specs) — must match verify_restore() in restore_engine.py
        # Hash uses Tier 1 fields only (excludes "audit" key)
        all_hashes = []
        for rel_path, props in sorted(entity_overrides.items()):
            if not props:
                continue
            h = _compute_prim_hash(props)
            all_hashes.append(h)

            prim_snapshots.append({
                "entity_path": entity_path,
                "relative_path": rel_path[len(entity_path):] or "/",
                "prim_type": props.get("typeName", "Unknown"),
                "properties": json.dumps(props, sort_keys=True, default=str),
                "prim_hash": h,
            })

        combined_hash = hashlib.sha256(
            "".join(sorted(all_hashes)).encode()
        ).hexdigest()[:16]

        # Build depends_on: entity paths referenced via rel: keys in override properties
        depends_on = _extract_depends_on(entity_overrides, entity_path, entity_paths)

        entities.append({
            "entity_id": str(uuid.uuid5(uuid.NAMESPACE_URL, entity_path)),
            "entity_path": entity_path,
            "entity_type": info["type"],
            "source_type": info["source_type"],
            "source_asset": info.get("source_asset", ""),
            "child_count": len(entity_overrides),
            "entity_hash": combined_hash,
            "usd_file_path": "",
            "depends_on": json.dumps(depends_on),
        })

    return entities, prim_snapshots, asset_urls


def _get_all_list_items(list_op) -> list:
    """Get all items from a Sdf ListOp (prepended + appended + explicit).

    USD references/payloads can be authored as prepend, append, or explicit.
    Isaac Sim typically uses explicit items for drag-and-drop references.
    """
    items = []
    for attr_name in ("prependedItems", "appendedItems", "explicitItems"):
        sub = getattr(list_op, attr_name, None)
        if sub:
            items.extend(sub)
    return items


def _traverse_layer_for_entities(layer, path: str, entity_paths: dict):
    """Recursively traverse Sdf Layer to find all entities (Reference/Payload/Container).

    Unlike stage.Traverse() with LoadNone, this finds Payload prims too.
    """
    prim_spec = layer.GetPrimAtPath(path)
    if not prim_spec:
        return

    for child in prim_spec.nameChildren:
        child_path = f"{path}/{child.name}"
        child_spec = layer.GetPrimAtPath(child_path)
        if not child_spec:
            continue

        refs = _get_all_list_items(child_spec.referenceList)
        pays = _get_all_list_items(child_spec.payloadList)

        if refs or pays:
            source_type = "reference" if refs else "payload"
            source_asset = str(refs[0].assetPath) if refs else str(pays[0].assetPath) if pays else ""
            entity_paths[child_path] = {
                "type": child_spec.typeName or "Xform",
                "source_type": source_type,
                "source_asset": source_asset,
            }
        elif path == "/World":
            # Container Xform directly under /World
            entity_paths[child_path] = {
                "type": child_spec.typeName or "Xform",
                "source_type": "container",
                "source_asset": "",
            }

        # Recurse into children (for nested entities inside containers)
        _traverse_layer_for_entities(layer, child_path, entity_paths)


def _traverse_stage_for_entities(stage, path: str, entity_paths: dict):
    """Traverse composed Stage to find all entities.

    Unlike _traverse_layer_for_entities (Sdf.Layer only), this sees prims from
    sublayers too — covers the full composed /World hierarchy.
    """
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return

    for child in prim.GetChildren():
        child_path = str(child.GetPath())

        has_refs = child.HasAuthoredReferences()
        has_pays = child.HasAuthoredPayloads()

        if has_refs or has_pays:
            source_type, source_asset = _get_composition_source(child)
            entity_paths[child_path] = {
                "type": child.GetTypeName() or "Xform",
                "source_type": source_type,
                "source_asset": source_asset,
            }
        elif path == "/World":
            # Container Xform directly under /World (no composition arc)
            entity_paths[child_path] = {
                "type": child.GetTypeName() or "Xform",
                "source_type": "container",
                "source_asset": "",
            }

        # Recurse into children (for nested entities inside containers)
        _traverse_stage_for_entities(stage, child_path, entity_paths)


def _get_composition_source(prim) -> tuple[str, str]:
    """Extract source_type and source_asset from a prim's composition arcs.

    Searches through all layers in the prim stack (root + sublayers) to find
    the Reference or Payload arc, regardless of which layer authored it.
    """
    try:
        for spec in prim.GetPrimStack():
            refs = _get_all_list_items(spec.referenceList)
            if refs:
                return "reference", str(refs[0].assetPath)
            pays = _get_all_list_items(spec.payloadList)
            if pays:
                return "payload", str(pays[0].assetPath)
    except Exception:
        pass
    # HasAuthoredPayloads/References was true but we couldn't find the arc detail
    if prim.HasAuthoredPayloads():
        return "payload", ""
    return "reference", ""


def _collect_overrides_recursive(
    layer, prim_path: str, entity_paths: dict | None = None, _root_path: str | None = None
) -> dict[str, dict]:
    """Collect all authored overrides for a prim and its children from a Sdf layer.

    Args:
        layer: Sdf.Layer (root layer)
        prim_path: USD prim path string
        entity_paths: dict of all known entity paths; children that are separate
                      entities are skipped to avoid cross-entity override inclusion
        _root_path: the top-level entity path being collected (set on first call)

    Returns:
        {full_prim_path: {prop_name: value, ...}} for every prim with overrides
    """
    from pxr import Sdf

    if _root_path is None:
        _root_path = prim_path

    result = {}
    layer_prim = layer.GetPrimAtPath(prim_path)
    if not layer_prim:
        return result

    # Extract overrides for this prim
    props = _extract_layer_overrides(layer_prim)
    # Always include — even empty props — so _cleanup_residual_prims won't strip this prim
    result[prim_path] = props

    # Recurse into children, stopping at nested entity boundaries
    for child_spec in layer_prim.nameChildren:
        child_path = f"{prim_path}/{child_spec.name}"
        # Skip children that are their own entity (prevents cross-entity hash contamination)
        if entity_paths is not None and child_path in entity_paths and child_path != _root_path:
            continue
        child_overrides = _collect_overrides_recursive(layer, child_path, entity_paths, _root_path)
        result.update(child_overrides)

    return result


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


def _extract_layer_overrides(layer_prim) -> dict[str, Any]:
    """Extract ALL authored overrides from Sdf.PrimSpec using field-driven approach.

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
                continue  # Skip unsupported crate file types (e.g. enum value 0)
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


def _to_json_value(val: Any) -> Any:
    """Convert a USD/Sdf value to a JSON-serializable Python type."""
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
    # AssetPath (e.g. info:mdl:sourceAsset on Shader prims)
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
                # Nested vector (Vec3f, Vec2f, etc.) — decompose to components
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


def _extract_depends_on(
    entity_overrides: dict[str, dict], entity_path: str, entity_paths: dict
) -> list[str]:
    """Extract cross-entity dependencies from relationship properties.

    Scans all overrides for relationship targets (nested dict: props.{name}.targets)
    and checks if their target paths belong to a different entity in entity_paths.

    Returns:
        Sorted, deduplicated list of entity_paths this entity depends on.
    """
    deps: set[str] = set()
    for props in entity_overrides.values():
        props_dict = props.get("props", {})
        for prop_name, prop_data in props_dict.items():
            targets_data = prop_data.get("targets")
            if not targets_data:
                continue
            # targets_data is a ListOp dict like {"explicit": [...], "prepended": [...]}
            target_paths = []
            if isinstance(targets_data, dict):
                for slot_targets in targets_data.values():
                    if isinstance(slot_targets, list):
                        target_paths.extend(slot_targets)
            elif isinstance(targets_data, list):
                target_paths = targets_data

            for target_str in target_paths:
                # Find the entity this target belongs to (longest prefix match)
                matched = None
                for ep in entity_paths:
                    if ep == entity_path:
                        continue
                    if target_str == ep or target_str.startswith(ep + "/"):
                        if matched is None or len(ep) > len(matched):
                            matched = ep
                if matched is not None:
                    deps.add(matched)
    return sorted(deps)
