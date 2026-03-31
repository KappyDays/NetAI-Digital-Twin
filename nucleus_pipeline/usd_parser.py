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

    # Use Sdf Layer API directly — stage.Traverse() with LoadNone misses Payload prims
    root_layer = Sdf.Layer.FindOrOpen(file_path)
    if not root_layer:
        raise RuntimeError(f"Failed to open USD layer: {file_path}")

    # Step 1: Identify entities via Sdf Layer traversal
    # Includes: Reference/Payload prims AND container Xforms under /World
    entity_paths = {}
    _traverse_layer_for_entities(root_layer, "/World", entity_paths)

    # Step 2: Extract overrides from root layer (Sdf API)
    entities = []
    prim_snapshots = []
    asset_urls = {}  # {entity_path: original_url}

    for entity_path, info in entity_paths.items():
        # Include ALL entity asset URLs regardless of protocol (https://, omniverse://)
        if info["source_asset"]:
            asset_urls[entity_path] = info["source_asset"]

        # Collect overrides for this entity and its children from root layer
        entity_overrides = _collect_overrides_recursive(root_layer, entity_path)

        # Compute combined hash from all sub-prim overrides
        all_hashes = []
        for rel_path, props in sorted(entity_overrides.items()):
            props_json = json.dumps(props, sort_keys=True, default=str)
            h = hashlib.sha256(props_json.encode()).hexdigest()[:16]
            all_hashes.append(h)

            prim_snapshots.append({
                "entity_path": entity_path,
                "relative_path": rel_path.replace(entity_path, "") or "/",
                "prim_type": props.get("typeName", "Unknown"),
                "properties": props_json,
                "prim_hash": h,
            })

        combined_hash = hashlib.sha256(
            "".join(sorted(all_hashes)).encode()
        ).hexdigest()[:16]

        entities.append({
            "entity_id": str(uuid.uuid4()),
            "entity_path": entity_path,
            "entity_type": info["type"],
            "source_type": info["source_type"],
            "source_asset": info.get("source_asset", ""),
            "is_dynamic": False,
            "dynamic_table": "",
            "child_count": len(entity_overrides),
            "entity_hash": combined_hash,
            "usd_file_path": "",
        })

    return entities, prim_snapshots, asset_urls


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

        refs = list(child_spec.referenceList.prependedItems) if child_spec.referenceList.prependedItems else []
        pays = list(child_spec.payloadList.prependedItems) if child_spec.payloadList.prependedItems else []

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


def _collect_overrides_recursive(layer, prim_path: str) -> dict[str, dict]:
    """Collect all authored overrides for a prim and its children from a Sdf layer.

    Args:
        layer: Sdf.Layer (root layer)
        prim_path: USD prim path string

    Returns:
        {full_prim_path: {prop_name: value, ...}} for every prim with overrides
    """
    from pxr import Sdf

    result = {}
    layer_prim = layer.GetPrimAtPath(prim_path)
    if not layer_prim:
        return result

    # Extract overrides for this prim
    props = _extract_layer_overrides(layer_prim)
    if props:
        result[prim_path] = props

    # Recurse into children
    for child_spec in layer_prim.nameChildren:
        child_path = f"{prim_path}/{child_spec.name}"
        child_overrides = _collect_overrides_recursive(layer, child_path)
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

    return props


def _to_json_value(val: Any) -> Any:
    """Convert a USD/Sdf value to a JSON-serializable Python type."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    if hasattr(val, "__len__") and not isinstance(val, str):
        try:
            return [float(v) for v in val]
        except (TypeError, ValueError):
            return str(val)
    return str(val)


def generate_root_usda(source_path: str, asset_urls: dict[str, str], output_path: str):
    """Generate root.usda: copy source layer as-is, preserving original Reference/Payload URLs.

    USD entity files are NOT self-contained — they depend on sibling files
    (sublayers, textures, materials) via relative paths. Rewriting URLs to
    ./entities/*.usd breaks these internal references.

    Instead, root.usda keeps original absolute URLs so Isaac Sim can resolve
    all dependencies from the original source (NVIDIA CDN, Nucleus server).
    Entity USD copies in MinIO serve as archival backups.

    Args:
        source_path: Path to the original downloaded USD file
        asset_urls: {entity_path: original_url} (for reference, not rewritten)
        output_path: Where to write the root.usda copy
    """
    import shutil
    shutil.copy2(source_path, output_path)
    return output_path
