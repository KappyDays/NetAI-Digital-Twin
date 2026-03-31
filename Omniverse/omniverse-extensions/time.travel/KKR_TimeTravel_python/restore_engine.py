"""Time Travel Restore Engine — Stage/Entity restore + Undo snapshot logic.

Handles:
- Property override application (reused from lakehouse.proto _apply_property_overrides)
- Undo snapshot capture (root layer overrides → Python dict)
- Stage-wide restore (3 modes)
- Entity-level restore
"""

import json
from typing import Any

import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom


# ═══════════════════════════════════════════════════════════════════════
#  Undo Snapshot — Capture current Stage root layer overrides
# ═══════════════════════════════════════════════════════════════════════

def capture_undo_snapshot() -> dict:
    """Capture current Stage root layer overrides as a Python dict.

    Returns:
        {prim_path: {prop_name: value, ...}, ...}
        Captures the same data scope as Task 2 (usd_parser.py).
    """
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return {}

    root_layer = stage.GetRootLayer()
    if not root_layer:
        return {}

    snapshot = {}
    world_spec = root_layer.GetPrimAtPath("/World")
    if not world_spec:
        return {}

    _collect_layer_overrides_recursive(root_layer, "/World", snapshot)
    return snapshot


def _collect_layer_overrides_recursive(layer, prim_path: str, result: dict):
    """Recursively collect all authored overrides from a Sdf layer."""
    prim_spec = layer.GetPrimAtPath(prim_path)
    if not prim_spec:
        return

    props = _extract_layer_overrides(prim_spec)
    if props:
        result[prim_path] = props

    for child_spec in prim_spec.nameChildren:
        child_path = f"{prim_path}/{child_spec.name}"
        _collect_layer_overrides_recursive(layer, child_path, result)


def _extract_layer_overrides(layer_prim) -> dict:
    """Extract all authored overrides from a Sdf.PrimSpec."""
    props = {}

    type_name = layer_prim.typeName
    if type_name:
        props["typeName"] = type_name

    for prop_spec in layer_prim.properties:
        prop_name = prop_spec.name
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


def _to_json_value(val) -> Any:
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


# ═══════════════════════════════════════════════════════════════════════
#  Apply Undo — Restore from memory snapshot
# ═══════════════════════════════════════════════════════════════════════

def apply_undo_snapshot(snapshot: dict) -> tuple[int, int, list]:
    """Apply a previously captured undo snapshot to the current Stage.

    Args:
        snapshot: {prim_path: {prop_name: value, ...}, ...}

    Returns:
        (applied_count, failed_count, warnings_list)
    """
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


# ═══════════════════════════════════════════════════════════════════════
#  Stage Restore — Apply backup data to current Stage
# ═══════════════════════════════════════════════════════════════════════

# Restore modes
MODE_CHANGES_ONLY = "changes_only"
MODE_FULL_ENTITY = "full_entity"
MODE_FULL_ALL = "full_all"


def restore_stage(
    entities: list[dict],
    prim_snapshots: list[dict],
    mode: str = MODE_CHANGES_ONLY,
    progress_callback=None,
) -> tuple[int, int, int, int, list]:
    """Restore entire Stage from backup data.

    Args:
        entities: List of entity dicts from API
        prim_snapshots: List of prim snapshot dicts from API
        mode: MODE_CHANGES_ONLY | MODE_FULL_ENTITY | MODE_FULL_ALL
        progress_callback: Optional fn(current, total, entity_path) for progress

    Returns:
        (entities_restored, props_applied, props_failed, prims_deleted, warnings)
    """
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return 0, 0, 0, 0, ["No active Stage"]

    # Group prim_snapshots by entity_path
    snaps_by_entity = {}
    for snap in prim_snapshots:
        ep = snap.get("entity_path", "")
        if ep not in snaps_by_entity:
            snaps_by_entity[ep] = []
        snaps_by_entity[ep].append(snap)

    backup_entity_paths = {e["entity_path"] for e in entities}
    entities_restored = 0
    total_applied = 0
    total_failed = 0
    total_deleted = 0
    all_warnings = []

    # 1. Apply overrides for each backed-up entity
    total = len(entities)
    for i, entity in enumerate(entities):
        ep = entity["entity_path"]
        if progress_callback:
            progress_callback(i + 1, total, ep)

        entity_snaps = snaps_by_entity.get(ep, [])
        a, f, w = apply_entity_overrides(stage, ep, entity_snaps)
        total_applied += a
        total_failed += f
        all_warnings.extend(w)
        if a > 0 or f > 0:
            entities_restored += 1

    # 2. Handle deletion based on mode
    if mode in (MODE_FULL_ENTITY, MODE_FULL_ALL):
        world_prim = stage.GetPrimAtPath("/World")
        if world_prim.IsValid():
            for child in world_prim.GetChildren():
                child_path = str(child.GetPath())
                if child_path in backup_entity_paths:
                    continue

                if mode == MODE_FULL_ENTITY:
                    # Only delete if it looks like an entity (has ref/payload or is Xform under /World)
                    # Protect non-entity scopes: Looks, Camera_presets, etc.
                    child_type = child.GetTypeName()
                    if child_type in ("Scope",):
                        continue  # Protect Scope-type prims (Looks, Camera_presets)

                # Delete this prim
                stage.RemovePrim(child_path)
                total_deleted += 1

    return entities_restored, total_applied, total_failed, total_deleted, all_warnings


def restore_single_entity(
    entity_path: str,
    prim_snapshots: list[dict],
) -> tuple[int, int, list]:
    """Restore a single entity from backup data.

    Args:
        entity_path: The entity prim path
        prim_snapshots: List of prim snapshot dicts for this entity

    Returns:
        (props_applied, props_failed, warnings)
    """
    stage = omni.usd.get_context().get_stage()
    if not stage:
        return 0, 0, ["No active Stage"]

    return apply_entity_overrides(stage, entity_path, prim_snapshots)


def apply_entity_overrides(
    stage, entity_path: str, prim_snapshots: list[dict],
) -> tuple[int, int, list]:
    """Apply prim snapshot overrides to a single entity in the Stage.

    Args:
        stage: The USD Stage
        entity_path: e.g. "/World/AI_Grad_Building"
        prim_snapshots: List of {relative_path, prim_type, properties, prim_hash}

    Returns:
        (applied_count, failed_count, warnings_list)
    """
    total_applied = 0
    total_failed = 0
    warnings = []

    for snap in prim_snapshots:
        rel_path = snap.get("relative_path", "/")
        if rel_path == "/":
            full_path = entity_path
        else:
            full_path = entity_path + rel_path

        prim = stage.GetPrimAtPath(full_path)
        if not prim.IsValid():
            # Try to create the prim if it doesn't exist
            prim_type = snap.get("prim_type", "Xform")
            prim = stage.DefinePrim(full_path, prim_type)
            if not prim.IsValid():
                warnings.append(f"Cannot create prim: {full_path}")
                continue

        # Parse properties JSON
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


# ═══════════════════════════════════════════════════════════════════════
#  Property Application — Core override logic
# ═══════════════════════════════════════════════════════════════════════

def _apply_properties_to_prim(stage, prim, props: dict) -> tuple[int, int, list]:
    """Apply a dict of properties to a single USD prim.

    Handles xformOps, relationships, metadata, and regular attributes.
    Returns (applied, failed, warnings).
    """
    applied = 0
    failed = 0
    warnings = []

    # Classify properties
    xform_ops = {}
    relationships = {}
    metadata = {}
    regular_attrs = {}

    for key, val in props.items():
        if key == "typeName":
            continue
        elif key.startswith("xformOp:"):
            xform_ops[key] = val
        elif key.startswith("rel:"):
            relationships[key[4:]] = val
        elif key.startswith("meta:"):
            metadata[key[5:]] = val
        else:
            regular_attrs[key] = val

    # 1. Apply xformOps
    if xform_ops:
        xformable = UsdGeom.Xformable(prim)
        if xformable:
            # Build lookup of existing ops to avoid duplication
            existing_ops = {}
            for op in xformable.GetOrderedXformOps():
                existing_ops[op.GetOpName()] = op

            for op_name, op_val in xform_ops.items():
                try:
                    short_name = op_name.split(":")[-1]
                    if "translate" in short_name.lower():
                        if op_name in existing_ops:
                            xform_op = existing_ops[op_name]
                        else:
                            xform_op = xformable.AddTranslateOp()
                        if isinstance(op_val, list) and len(op_val) == 3:
                            xform_op.Set(Gf.Vec3d(*op_val))
                            applied += 1
                        else:
                            failed += 1
                            warnings.append(f"{prim.GetPath()}.{op_name}: invalid translate value")
                    elif "orient" in short_name.lower():
                        if op_name in existing_ops:
                            xform_op = existing_ops[op_name]
                        else:
                            xform_op = xformable.AddOrientOp()
                        if isinstance(op_val, list) and len(op_val) == 4:
                            xform_op.Set(Gf.Quatd(op_val[3], op_val[0], op_val[1], op_val[2]))
                            applied += 1
                        else:
                            failed += 1
                            warnings.append(f"{prim.GetPath()}.{op_name}: invalid orient value")
                    elif "rotatexyz" in short_name.lower() or "rotateXYZ" in short_name:
                        if op_name in existing_ops:
                            xform_op = existing_ops[op_name]
                        else:
                            xform_op = xformable.AddRotateXYZOp()
                        if isinstance(op_val, list) and len(op_val) == 3:
                            xform_op.Set(Gf.Vec3f(*[float(v) for v in op_val]))
                            applied += 1
                        else:
                            failed += 1
                            warnings.append(f"{prim.GetPath()}.{op_name}: invalid rotateXYZ value")
                    elif "scale" in short_name.lower():
                        if op_name in existing_ops:
                            xform_op = existing_ops[op_name]
                        else:
                            xform_op = xformable.AddScaleOp()
                        if isinstance(op_val, list) and len(op_val) == 3:
                            xform_op.Set(Gf.Vec3d(*op_val))
                            applied += 1
                        else:
                            failed += 1
                            warnings.append(f"{prim.GetPath()}.{op_name}: invalid scale value")
                    else:
                        if op_name in existing_ops:
                            xform_op = existing_ops[op_name]
                            _set_attr_value(xform_op.GetAttr(), op_val)
                            applied += 1
                        else:
                            attr = prim.GetAttribute(op_name)
                            if attr.IsValid():
                                _set_attr_value(attr, op_val)
                                applied += 1
                            else:
                                failed += 1
                                warnings.append(f"{prim.GetPath()}.{op_name}: attribute not found")
                except Exception as e:
                    failed += 1
                    warnings.append(f"{prim.GetPath()}.{op_name}: {e}")

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

    # 3. Apply metadata
    for meta_key, meta_val in metadata.items():
        try:
            if meta_key == "kind":
                Usd.ModelAPI(prim).SetKind(meta_val)
                applied += 1
            elif meta_key == "instanceable":
                prim.SetInstanceable(bool(meta_val))
                applied += 1
            elif meta_key == "active":
                prim.SetActive(bool(meta_val))
                applied += 1
            elif meta_key == "hidden":
                prim.SetHidden(bool(meta_val))
                applied += 1
            elif meta_key == "customData" and isinstance(meta_val, dict):
                for k, v in meta_val.items():
                    prim.SetCustomDataByKey(k, v)
                applied += 1
            elif meta_key == "assetInfo" and isinstance(meta_val, dict):
                for k, v in meta_val.items():
                    prim.SetAssetInfoByKey(k, v)
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
            if attr.IsValid():
                _set_attr_value(attr, attr_val)
                applied += 1
            else:
                failed += 1
                warnings.append(f"{prim.GetPath()}.{attr_name}: attribute not found")
        except Exception as e:
            failed += 1
            warnings.append(f"{prim.GetPath()}.{attr_name}: {e}")

    return applied, failed, warnings


def _set_attr_value(attr, val):
    """Set a USD attribute value, converting Python types to USD types."""
    current = attr.Get()
    if current is None:
        attr.Set(val)
        return

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
                attr.Set(Gf.Vec3f(*val))
            elif isinstance(current, Gf.Vec3h):
                attr.Set(Gf.Vec3h(*val))
            else:
                attr.Set(val)
        elif len(val) == 4:
            if isinstance(current, Gf.Vec4d):
                attr.Set(Gf.Vec4d(*val))
            elif isinstance(current, Gf.Vec4f):
                attr.Set(Gf.Vec4f(*val))
            elif isinstance(current, Gf.Quatd):
                attr.Set(Gf.Quatd(val[3], val[0], val[1], val[2]))
            elif isinstance(current, Gf.Quatf):
                attr.Set(Gf.Quatf(val[3], val[0], val[1], val[2]))
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
