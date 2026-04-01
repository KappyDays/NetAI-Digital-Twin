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
    from pxr import Sdf

    root_layer = Sdf.Layer.FindOrOpen(file_path)
    if not root_layer:
        raise RuntimeError(f"Failed to open USD layer: {file_path}")

    # Step 1: Identify entities
    # Primary: Sdf.Layer traversal — reliable for root layer content,
    # correctly detects both references AND payloads (LoadNone hides payloads).
    entity_paths = {}
    _traverse_layer_for_entities(root_layer, "/World", entity_paths)

    # Supplementary: Stage traversal for sublayer prims not in root layer.
    # Uses default load (not LoadNone) so payload prims are visible.
    if root_layer.subLayerPaths:
        try:
            from pxr import Usd
            stage = Usd.Stage.Open(root_layer)
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
        all_hashes = []
        for rel_path, props in sorted(entity_overrides.items()):
            props_json = json.dumps(props, sort_keys=True, default=str)
            h = hashlib.sha256(props_json.encode()).hexdigest()[:16]
            all_hashes.append(h)

            prim_snapshots.append({
                "entity_path": entity_path,
                "relative_path": rel_path[len(entity_path):] or "/",
                "prim_type": props.get("typeName", "Unknown"),
                "properties": props_json,
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
            "is_dynamic": False,
            "dynamic_table": "",
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
    if props:
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


def _extract_layer_overrides(layer_prim) -> dict[str, Any]:
    """Extract all authored overrides from a Sdf.PrimSpec.

    Captures:
    - Attributes (xformOp:translate, visibility, purpose, etc.)
    - Relationships (material:binding, etc.)
    - Metadata (kind, instanceable, active, hidden, customData, assetInfo)
    """
    props = {}

    # Type name
    type_name = layer_prim.typeName
    if type_name:
        props["typeName"] = type_name

    # Note: specifier (def/over/class) is intentionally NOT captured here.
    # It is Sdf layer metadata that cannot be applied via prim attribute API,
    # and including it would cause hash divergence with restore_engine.py.

    # Authored attribute overrides
    for prop_spec in layer_prim.properties:
        prop_name = prop_spec.name

        # AttributeSpec — has default value
        if hasattr(prop_spec, "default") and prop_spec.default is not None:
            props[prop_name] = _to_json_value(prop_spec.default)
        elif hasattr(prop_spec, "HasInfo") and prop_spec.HasInfo("timeSamples"):
            ts = prop_spec.GetInfo("timeSamples")
            if ts:
                props[prop_name] = {str(k): _to_json_value(v) for k, v in ts.items()}
        elif hasattr(prop_spec, "targetPathList"):
            targets = list(prop_spec.targetPathList.explicitItems)
            if targets:
                props[f"rel:{prop_name}"] = [str(t) for t in targets]

    # Metadata
    for key in layer_prim.ListInfoKeys():
        if key == "kind":
            props["meta:kind"] = layer_prim.GetInfo("kind")
        elif key == "instanceable":
            props["meta:instanceable"] = layer_prim.GetInfo("instanceable")
        elif key == "active":
            props["meta:active"] = layer_prim.GetInfo("active")
        elif key == "hidden":
            props["meta:hidden"] = layer_prim.GetInfo("hidden")
        elif key == "customData":
            cd = layer_prim.GetInfo("customData")
            if cd:
                props["meta:customData"] = {str(k): str(v) for k, v in cd.items()}
        elif key == "assetInfo":
            ai = layer_prim.GetInfo("assetInfo")
            if ai:
                props["meta:assetInfo"] = {str(k): str(v) for k, v in ai.items()}
        elif key == "apiSchemas":
            api_list_op = layer_prim.GetInfo("apiSchemas")
            api_data = {}
            if hasattr(api_list_op, "prependedItems") and api_list_op.prependedItems:
                api_data["prepend"] = [str(t) for t in api_list_op.prependedItems]
            if hasattr(api_list_op, "deletedItems") and api_list_op.deletedItems:
                api_data["delete"] = [str(t) for t in api_list_op.deletedItems]
            if hasattr(api_list_op, "appendedItems") and api_list_op.appendedItems:
                api_data["append"] = [str(t) for t in api_list_op.appendedItems]
            if hasattr(api_list_op, "explicitItems") and api_list_op.explicitItems:
                api_data["explicit"] = [str(t) for t in api_list_op.explicitItems]
            if api_data:
                props["meta:apiSchemas"] = api_data
        elif key == "variantSetNames":
            vs = layer_prim.GetInfo("variantSetNames")
            if vs:
                props["meta:variantSetNames"] = list(vs)
        elif key == "variantSelection":
            vsel = layer_prim.GetInfo("variantSelection")
            if vsel:
                props["meta:variantSelection"] = dict(vsel)

    return props


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
            if hasattr(v, "__len__"):
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

    Scans all overrides for keys starting with "rel:" and checks if their target
    paths belong to a different entity in entity_paths.

    Returns:
        Sorted, deduplicated list of entity_paths this entity depends on.
    """
    deps: set[str] = set()
    for props in entity_overrides.values():
        for key, val in props.items():
            if not key.startswith("rel:"):
                continue
            targets = val if isinstance(val, list) else [val]
            for target in targets:
                target_str = str(target)
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
