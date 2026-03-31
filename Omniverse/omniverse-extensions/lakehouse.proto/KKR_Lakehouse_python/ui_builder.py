# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import hashlib
import json
import os
import tempfile
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style
from pxr import Sdf, Usd, UsdGeom

# API middleware URL (env-var-driven for Docker/k8s portability).
DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        # Backup state
        self._last_backup_time = None
        self._backup_entity_count = 0
        self._backup_prim_count = 0
        # Restore state
        self._backup_times_list = []
        self._restore_entities_list = []
        self._selected_backup_idx = 0
        self._selected_entity_idx = 0

    # =========================================================================
    #  Automatic callbacks wired by extension.py
    # =========================================================================

    def on_menu_callback(self):
        pass

    def on_timeline_event(self, event):
        pass

    def on_physics_step(self, step):
        pass

    def on_stage_event(self, event):
        pass

    def cleanup(self):
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()

    def build_ui(self):
        self._create_status_frame()
        self._create_api_config_frame()
        self._create_stage_management_frame()
        self._create_entity_backup_frame()
        self._create_entity_restore_frame()
        self._create_sample_iot_frame()

    # =========================================================================
    #  Status Log
    # =========================================================================

    def _create_status_frame(self):
        self._status_frame = CollapsableFrame("Status / Log", collapsed=False)
        with self._status_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._status_field = TextBlock(
                    "Last Operation",
                    num_lines=5,
                    tooltip="Operation results and logs",
                    include_copy_button=True,
                )

    def _set_status(self, message: str):
        self._status_field.set_text(message)

    # =========================================================================
    #  API Middleware Configuration
    # =========================================================================

    def _create_api_config_frame(self):
        frame = CollapsableFrame("API Middleware Settings", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Enter the Lakehouse API middleware (FastAPI) address.\n"
                    "Use the default if the Docker container is on the same server.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )
                self._api_url_field = StringField(
                    "API Base URL",
                    default_value=DEFAULT_API_BASE_URL,
                    tooltip="Lakehouse API middleware URL (e.g. http://localhost:8100)",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._api_url_field)

                btn = Button(
                    "Health Check",
                    "PING API",
                    tooltip="Check API server connection status",
                    on_click_fn=self._on_health_check,
                )
                self.wrapped_ui_elements.append(btn)

    def _get_api_url(self) -> str:
        return self._api_url_field.get_value().rstrip("/")

    def _on_health_check(self):
        try:
            result = self._api_get("api/v1/health")
            self._set_status(f"[OK] API connected: {result}")
        except Exception as e:
            self._set_status(f"[FAIL] Cannot connect to API: {e}")

    # =========================================================================
    #  Stage Management (Setup / Clear)
    # =========================================================================

    def _create_stage_management_frame(self):
        frame = CollapsableFrame("Stage Management", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Setup a test Stage with 3 Xform groups (Environment, Robots, Props)\n"
                    "using Nucleus Reference assets, or clear the Stage.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )
                btn_setup = Button(
                    "Stage Setup",
                    "SETUP STAGE",
                    tooltip="Create /World with 3 Xform groups + Reference assets",
                    on_click_fn=self._on_stage_setup,
                )
                self.wrapped_ui_elements.append(btn_setup)

                btn_clear = Button(
                    "Stage Clear",
                    "CLEAR STAGE",
                    tooltip="Remove all Prims under /World",
                    on_click_fn=self._on_stage_clear,
                )
                self.wrapped_ui_elements.append(btn_clear)

    def _on_stage_setup(self):
        """Create /World with 3 Xform groups + Nucleus Reference assets."""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                self._set_status("[FAIL] No active Stage. Open or create a Stage first.")
                return

            # Ensure /World exists as default prim
            world_prim = stage.GetPrimAtPath("/World")
            if not world_prim.IsValid():
                UsdGeom.Xform.Define(stage, "/World")
                stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))

            # Get Nucleus assets root
            try:
                from isaacsim.storage.native import get_assets_root_path
                root = get_assets_root_path()
            except Exception:
                root = None

            if not root:
                self._set_status(
                    "[FAIL] Nucleus not connected. Cannot load Reference assets.\n"
                    "Connect to Nucleus first (Omniverse > Nucleus)."
                )
                return

            # ── Xform 1: Environment ──
            UsdGeom.Xform.Define(stage, "/World/Environment")
            self._add_reference(stage, f"{root}/Isaac/Environments/Grid/default_environment.usd", "/World/Environment/Grid")
            self._add_reference(stage, f"{root}/Isaac/Props/Mounts/ThorlabsTable/table_instanceable.usd", "/World/Environment/Table")

            # ── Xform 2: Robots ──
            UsdGeom.Xform.Define(stage, "/World/Robots")
            self._add_reference(stage, f"{root}/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd", "/World/Robots/Jetbot")
            self._add_reference(stage, f"{root}/Isaac/Robots/NVIDIA/Kaya/kaya.usd", "/World/Robots/Kaya")

            # ── Xform 3: Props ──
            UsdGeom.Xform.Define(stage, "/World/Props")
            self._add_reference(stage, f"{root}/Isaac/Props/Blocks/basic_block.usd", "/World/Props/Block_A")
            self._add_reference(stage, f"{root}/Isaac/Props/Blocks/basic_block.usd", "/World/Props/Block_B")

            self._set_status(
                "[OK] Stage Setup complete.\n"
                "Created: /World/Environment (Grid, Table)\n"
                "         /World/Robots (Jetbot, Kaya)\n"
                "         /World/Props (Block_A, Block_B)"
            )
        except Exception as e:
            self._set_status(f"[FAIL] Stage Setup error:\n{traceback.format_exc()}")

    @staticmethod
    def _add_reference(stage, asset_path: str, prim_path: str):
        """Add a USD Reference to the stage at the given prim path."""
        prim = stage.DefinePrim(prim_path)
        prim.GetReferences().AddReference(asset_path)

    def _on_stage_clear(self):
        """Remove all Prims under /World."""
        try:
            stage = omni.usd.get_context().get_stage()
            if not stage:
                self._set_status("[FAIL] No active Stage.")
                return

            world_prim = stage.GetPrimAtPath("/World")
            if not world_prim.IsValid():
                self._set_status("[INFO] /World does not exist. Nothing to clear.")
                return

            children = list(world_prim.GetChildren())
            count = len(children)
            for child in children:
                stage.RemovePrim(child.GetPath())

            self._set_status(f"[OK] Stage Clear: removed {count} child Prim(s) under /World.")
        except Exception as e:
            self._set_status(f"[FAIL] Stage Clear error:\n{traceback.format_exc()}")

    # =========================================================================
    #  Entity Backup
    # =========================================================================

    def _create_entity_backup_frame(self):
        frame = CollapsableFrame("Entity Backup", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Scan the Stage for Entity boundaries (Reference/Payload),\n"
                    "compute hashes, export USD binaries to MinIO, and save\n"
                    "Entity + Prim Snapshot data to Iceberg.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                btn = Button(
                    "Entity Backup to Lakehouse",
                    "BACKUP",
                    tooltip="Run full Entity backup (Iceberg + MinIO)",
                    on_click_fn=self._on_entity_backup,
                )
                self.wrapped_ui_elements.append(btn)

                self._backup_status_label = ui.Label(
                    "Status: Ready",
                    word_wrap=True,
                    style={"color": 0xFF88FF88, "font_size": 13},
                )

    def _on_entity_backup(self):
        """Full Entity backup: scan stage → hash → export USD → API call."""
        try:
            self._backup_status_label.text = "Status: Backing up..."
            stage = omni.usd.get_context().get_stage()
            if not stage:
                self._set_status("[FAIL] No active Stage.")
                self._backup_status_label.text = "Status: Failed (no Stage)"
                return

            backup_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

            # 0. Flatten the stage to get a consistent snapshot layer
            #    (merges all Layer overrides into composed values for USD export)
            self._flat_layer = stage.Flatten()

            # 1. Find entities (Reference/Payload boundaries)
            #    Property extraction uses live stage (composed values via .Get())
            entities = self._find_entities(stage)
            if not entities:
                self._set_status("[INFO] No entities found on Stage. Run Stage Setup first.")
                self._backup_status_label.text = "Status: No entities found"
                return

            # 2. For each entity, collect sub-prims, compute hashes, export USD
            entity_rows = []
            prim_rows = []

            for entity_path, info in entities.items():
                member_prims = info["members"]
                prim_hashes = []

                for prim in member_prims:
                    rel_path = str(prim.GetPath()).replace(entity_path, "") or "/"
                    props = self._extract_properties(prim)
                    props_json = json.dumps(props, sort_keys=True, default=str)
                    prim_hash = hashlib.sha256(props_json.encode()).hexdigest()[:16]
                    prim_hashes.append(prim_hash)

                    prim_rows.append({
                        "entity_path": entity_path,
                        "relative_path": rel_path,
                        "prim_type": prim.GetTypeName() or "Unknown",
                        "properties": props_json,
                        "prim_hash": prim_hash,
                    })

                entity_hash = hashlib.sha256(
                    "".join(sorted(prim_hashes)).encode()
                ).hexdigest()[:16]

                # 3. Export entity subtree as USD file → MinIO
                usd_file_path = ""
                try:
                    usd_file_path = self._export_and_upload_entity(
                        stage, entity_path, backup_time
                    )
                except Exception as usd_exc:
                    self._set_status(f"[WARN] USD export failed for {entity_path}: {usd_exc}")

                entity_rows.append({
                    "entity_id": str(uuid.uuid4()),
                    "entity_path": entity_path,
                    "entity_type": info["type"],
                    "source_type": info["source_type"],
                    "source_asset": info.get("source_asset", ""),
                    "is_dynamic": False,
                    "dynamic_table": "",
                    "child_count": len(member_prims),
                    "entity_hash": entity_hash,
                    "usd_file_path": usd_file_path,
                })

            # 4. Send to API
            payload = {
                "backup_time": backup_time,
                "backup_source": "extension",
                "entities": entity_rows,
                "prim_snapshots": prim_rows,
            }
            result = self._api_post_json("api/v1/entities/backup", payload)

            self._last_backup_time = backup_time
            self._backup_entity_count = len(entity_rows)
            self._backup_prim_count = len(prim_rows)

            self._backup_status_label.text = (
                f"Status: Done | Last: {backup_time[:19]}\n"
                f"Entities: {len(entity_rows)}, Prims: {len(prim_rows)}"
            )
            self._set_status(
                f"[OK] Entity Backup complete.\n"
                f"Time: {backup_time}\n"
                f"Entities: {len(entity_rows)}, Prims: {len(prim_rows)}\n"
                f"API response: {result}"
            )
        except Exception as e:
            self._backup_status_label.text = "Status: Failed"
            self._set_status(f"[FAIL] Entity Backup error:\n{traceback.format_exc()}")

    def _find_entities(self, stage) -> dict:
        """Find Entity boundaries by scanning for Reference/Payload prims.

        Returns {entity_path: {"type": str, "source_type": str, "source_asset": str, "members": [Prim]}}.
        """
        entities = {}
        entity_paths_set = set()

        # First pass: identify all prims that ARE entities (have references or payloads)
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path == "/" or not path.startswith("/World"):
                continue

            has_ref = prim.HasAuthoredReferences()
            has_payload = prim.HasAuthoredPayloads()

            if has_ref or has_payload:
                source_type = "reference" if has_ref else "payload"
                source_asset = ""
                # Try to get the reference asset path
                if has_ref:
                    refs = prim.GetMetadata("references")
                    if refs:
                        prepend = refs.prependedItems if hasattr(refs, "prependedItems") else []
                        if prepend:
                            source_asset = str(prepend[0].assetPath) if hasattr(prepend[0], "assetPath") else ""

                entities[path] = {
                    "type": prim.GetTypeName() or "Xform",
                    "source_type": source_type,
                    "source_asset": source_asset,
                    "members": [],
                }
                entity_paths_set.add(path)

        # Second pass: assign each prim to its nearest entity ancestor
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path == "/" or not path.startswith("/World"):
                continue

            # Find nearest entity ancestor (including self)
            nearest = None
            for ep in entity_paths_set:
                if path == ep or path.startswith(ep + "/"):
                    if nearest is None or len(ep) > len(nearest):
                        nearest = ep

            if nearest and nearest in entities:
                entities[nearest]["members"].append(prim)

        # Handle inline prims (no entity ancestor) — treat as individual entities
        for prim in stage.Traverse():
            path = str(prim.GetPath())
            if path == "/" or not path.startswith("/World"):
                continue

            # Check if this prim is already covered
            covered = False
            for ep in entity_paths_set:
                if path == ep or path.startswith(ep + "/"):
                    covered = True
                    break

            if not covered:
                # Direct children of /World that aren't entities become standalone
                parent = str(prim.GetParent().GetPath()) if prim.GetParent() else ""
                if parent == "/World":
                    entities[path] = {
                        "type": prim.GetTypeName() or "Xform",
                        "source_type": "inline",
                        "source_asset": "",
                        "members": [prim],
                    }
                    entity_paths_set.add(path)

        return entities

    @staticmethod
    def _extract_properties(prim) -> dict:
        """Extract ALL authored/composed properties from a USD Prim.

        Captures:
        - Attributes: transforms, visibility, purpose, custom attrs
        - Relationships: material bindings, proxy targets, etc.
        - Metadata: kind, instanceable, active, hidden, customData, assetInfo
        """
        props = {}
        try:
            props["typeName"] = prim.GetTypeName()

            # ── 1. Attributes (transforms, visibility, purpose, etc.) ──
            for attr in prim.GetAttributes():
                if attr.HasAuthoredValue():
                    val = attr.Get()
                    name = attr.GetName()
                    if val is None:
                        props[name] = None
                    elif hasattr(val, "__len__") and not isinstance(val, str):
                        try:
                            props[name] = [float(v) for v in val]
                        except (TypeError, ValueError):
                            props[name] = str(val)
                    elif isinstance(val, (int, float, bool, str)):
                        props[name] = val
                    else:
                        props[name] = str(val)

            # ── 2. Relationships (material bindings, etc.) ──
            for rel in prim.GetRelationships():
                if rel.HasAuthoredTargets():
                    targets = rel.GetTargets()
                    name = rel.GetName()
                    props[f"rel:{name}"] = [str(t) for t in targets]

            # ── 3. Metadata ──
            from pxr import Usd

            # Kind
            model = Usd.ModelAPI(prim)
            kind = model.GetKind()
            if kind:
                props["meta:kind"] = kind

            # Instanceable
            if prim.HasAuthoredMetadata("instanceable"):
                props["meta:instanceable"] = prim.IsInstanceable()

            # Active
            if prim.HasAuthoredMetadata("active"):
                props["meta:active"] = prim.IsActive()

            # Hidden
            if prim.HasAuthoredMetadata("hidden"):
                props["meta:hidden"] = prim.IsHidden()

            # CustomData (user-defined key-value pairs)
            custom_data = prim.GetCustomData()
            if custom_data:
                props["meta:customData"] = {str(k): str(v) for k, v in custom_data.items()}

            # AssetInfo
            asset_info = prim.GetAssetInfo()
            if asset_info:
                props["meta:assetInfo"] = {str(k): str(v) for k, v in asset_info.items()}

        except Exception:
            pass
        return props

    def _export_and_upload_entity(self, stage, entity_path: str, backup_time: str) -> str:
        """Export an entity subtree as .usd file and upload to MinIO via API."""
        # Create a temporary USD file with just this entity's subtree
        safe_name = entity_path.strip("/").replace("/", "_")
        ts_safe = backup_time.replace(":", "-").replace(" ", "T")[:19]
        filename = f"{safe_name}_{ts_safe}.usd"

        tmp_dir = tempfile.gettempdir()
        tmp_path = os.path.join(tmp_dir, filename)

        try:
            # Export the subtree
            prim = stage.GetPrimAtPath(entity_path)
            if not prim.IsValid():
                return ""

            # Create a new stage and copy from the flattened layer
            # (uses composed values, merging all layer overrides)
            export_stage = Usd.Stage.CreateNew(tmp_path)
            source_layer = getattr(self, "_flat_layer", None) or stage.GetRootLayer()
            Sdf.CopySpec(
                source_layer,
                entity_path,
                export_stage.GetRootLayer(),
                entity_path,
            )
            export_stage.GetRootLayer().Save()

            # Upload via API
            result = self._api_post_file(
                "api/v1/upload-usd",
                tmp_path,
                fields={"prim_path": entity_path},
            )

            s3_key = result.get("s3_key", "")
            bucket = result.get("bucket", "")
            return f"s3://{bucket}/{s3_key}" if s3_key else ""
        finally:
            # Cleanup temp file
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def _download_usd_from_minio(self, s3_url: str) -> str:
        """Download a USD file from MinIO (s3://bucket/key) to a local temp file.

        Returns the local file path, or empty string on failure.
        """
        # Parse s3://bucket/key format
        if not s3_url.startswith("s3://"):
            return ""
        parts = s3_url[5:].split("/", 1)
        if len(parts) < 2:
            return ""
        bucket, key = parts[0], parts[1]

        # Build MinIO HTTP URL from API base URL
        # The API base is like http://lakehouse-api:8000, MinIO is at minio:9000
        # Use the API's upload endpoint to get S3 info, or construct MinIO URL directly
        api_base = self._get_api_url()
        # Replace lakehouse-api:8000 with minio:9000 for direct MinIO access
        minio_base = api_base.replace("lakehouse-api:8000", "minio:9000").replace(
            "localhost:8100", "localhost:9000"
        )
        download_url = f"{minio_base}/{bucket}/{key}"

        # Download to temp file
        safe_name = key.replace("/", "_")
        tmp_path = os.path.join(tempfile.gettempdir(), f"restore_{safe_name}")

        req = urllib.request.Request(download_url, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(tmp_path, "wb") as f:
                f.write(resp.read())

        return tmp_path

    @staticmethod
    def _apply_property_overrides(stage, entity_path: str, prim_snapshots: list) -> int:
        """Apply backed-up property values as overrides on the restored entity.

        Handles three categories:
        1. xformOps (translate, orient, scale, rotateXYZ) — created via UsdGeom.Xformable API
        2. Relationships (material bindings) — restored via Relationship API
        3. Regular attributes (visibility, purpose, custom) — set or created as needed

        Returns the number of properties successfully applied.
        """
        from pxr import Gf, Usd

        applied = 0
        for snap in prim_snapshots:
            rel_path = snap.get("relative_path", "/")
            props_json = snap.get("properties", "{}")
            full_path = entity_path + rel_path if rel_path != "/" else entity_path

            prim = stage.GetPrimAtPath(full_path)
            if not prim.IsValid():
                continue

            try:
                props = json.loads(props_json)
            except (json.JSONDecodeError, TypeError):
                continue

            # Separate properties into categories
            xform_ops = {}
            relationships = {}
            metadata = {}
            regular_attrs = {}

            for attr_name, attr_val in props.items():
                if attr_name == "typeName" or attr_name == "xformOpOrder":
                    continue
                elif attr_name.startswith("meta:"):
                    metadata[attr_name[5:]] = attr_val
                elif attr_name.startswith("rel:"):
                    relationships[attr_name[4:]] = attr_val
                elif attr_name.startswith("xformOp:"):
                    xform_ops[attr_name] = attr_val
                else:
                    regular_attrs[attr_name] = attr_val

            # ── 1. Apply xformOps via Xformable API ──────────────────
            if xform_ops:
                xformable = UsdGeom.Xformable(prim)
                # Clear any existing xformOpOrder to start fresh
                xformable.ClearXformOpOrder()

                # Apply in standard order: translate → orient/rotate → scale
                if "xformOp:translate" in xform_ops:
                    val = xform_ops["xformOp:translate"]
                    op = xformable.AddTranslateOp()
                    if isinstance(val, list) and len(val) == 3:
                        op.Set(Gf.Vec3d(val[0], val[1], val[2]))
                    applied += 1

                if "xformOp:orient" in xform_ops:
                    val = xform_ops["xformOp:orient"]
                    op = xformable.AddOrientOp()
                    if isinstance(val, list) and len(val) == 4:
                        op.Set(Gf.Quatd(val[3], val[0], val[1], val[2]))
                    applied += 1

                if "xformOp:rotateXYZ" in xform_ops:
                    val = xform_ops["xformOp:rotateXYZ"]
                    op = xformable.AddRotateXYZOp()
                    if isinstance(val, list) and len(val) == 3:
                        op.Set(Gf.Vec3f(val[0], val[1], val[2]))
                    applied += 1

                if "xformOp:scale" in xform_ops:
                    val = xform_ops["xformOp:scale"]
                    op = xformable.AddScaleOp()
                    if isinstance(val, list) and len(val) == 3:
                        op.Set(Gf.Vec3d(val[0], val[1], val[2]))
                    applied += 1

                # Handle any other xformOps not covered above
                for op_name, op_val in xform_ops.items():
                    if op_name in ("xformOp:translate", "xformOp:orient",
                                   "xformOp:rotateXYZ", "xformOp:scale"):
                        continue  # already handled
                    try:
                        attr = prim.GetAttribute(op_name)
                        if attr.IsValid():
                            UIBuilder._set_attr_value(attr, op_val)
                            applied += 1
                    except Exception:
                        pass

            # ── 2. Apply Relationships (material bindings, etc.) ──────
            for rel_name, targets in relationships.items():
                try:
                    rel = prim.GetRelationship(rel_name)
                    if not rel.IsValid():
                        rel = prim.CreateRelationship(rel_name)
                    if rel.IsValid() and isinstance(targets, list):
                        rel.SetTargets([Sdf.Path(t) for t in targets])
                        applied += 1
                except Exception:
                    pass

            # ── 3. Apply Metadata (kind, instanceable, active, hidden, customData, assetInfo) ──
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
                except Exception:
                    pass

            # ── 4. Apply regular attributes ───────────────────────────
            for attr_name, attr_val in regular_attrs.items():
                try:
                    attr = prim.GetAttribute(attr_name)
                    if attr.IsValid():
                        UIBuilder._set_attr_value(attr, attr_val)
                        applied += 1
                except Exception:
                    pass

        return applied

    @staticmethod
    def _set_attr_value(attr, val):
        """Set a USD attribute value, converting Python types to USD types."""
        from pxr import Gf
        current = attr.Get()
        if current is None:
            # Try to set directly
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
            # Match the existing type
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

    # =========================================================================
    #  Entity Restore
    # =========================================================================

    def _create_entity_restore_frame(self):
        frame = CollapsableFrame("Entity Restore", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Restore an entity from a previous backup.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # ── Backup Time row: [< PREV] [label] [NEXT >] ──
                ui.Label("Backup Time", style={"color": 0xFF999999, "font_size": 11})
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "<<", width=40, height=24,
                        clicked_fn=self._on_prev_backup_time,
                        tooltip="Previous backup time",
                    )
                    self._restore_time_label = ui.Label(
                        "(not loaded)",
                        alignment=ui.Alignment.CENTER,
                        style={"color": 0xFFEEEEEE, "font_size": 13},
                    )
                    ui.Button(
                        ">>", width=40, height=24,
                        clicked_fn=self._on_next_backup_time,
                        tooltip="Next backup time",
                    )

                # ── Entity row: [< PREV] [label] [NEXT >] ──
                ui.Label("Entity", style={"color": 0xFF999999, "font_size": 11})
                with ui.HStack(height=26, spacing=4):
                    ui.Button(
                        "<<", width=40, height=24,
                        clicked_fn=self._on_prev_entity,
                        tooltip="Previous entity",
                    )
                    self._restore_entity_label = ui.Label(
                        "(not loaded)",
                        alignment=ui.Alignment.CENTER,
                        style={"color": 0xFFEEEEEE, "font_size": 13},
                    )
                    ui.Button(
                        ">>", width=40, height=24,
                        clicked_fn=self._on_next_entity,
                        tooltip="Next entity",
                    )

                # ── Action buttons ──
                ui.Spacer(height=2)
                with ui.HStack(height=28, spacing=8):
                    ui.Button(
                        "Load Backup Times", height=26,
                        clicked_fn=self._on_load_backup_times,
                        tooltip="Fetch available backup timestamps from API",
                    )
                    ui.Button(
                        "Load Entities", height=26,
                        clicked_fn=self._on_load_entities_for_restore,
                        tooltip="Load entity list for selected backup time",
                    )
                ui.Button(
                    "Restore Selected Entity", height=30,
                    clicked_fn=self._on_restore_entity,
                    tooltip="Restore entity from backup to current Stage",
                    style={"Button": {"background_color": 0xFF2266AA}},
                )

    def _on_load_backup_times(self):
        try:
            result = self._api_get("api/v1/entities/backup-times")
            self._backup_times_list = result.get("backup_times", [])
            self._selected_backup_idx = 0
            if self._backup_times_list:
                self._restore_time_label.text = f"Backup Time: {self._backup_times_list[0]}"
                self._set_status(f"[OK] Loaded {len(self._backup_times_list)} backup time(s).")
            else:
                self._restore_time_label.text = "Backup Time: (no backups found)"
                self._set_status("[INFO] No backup times found.")
        except Exception as e:
            self._set_status(f"[FAIL] Load backup times error: {e}")

    def _on_prev_backup_time(self):
        if not self._backup_times_list:
            return
        self._selected_backup_idx = max(0, self._selected_backup_idx - 1)
        self._restore_time_label.text = f"Backup Time: {self._backup_times_list[self._selected_backup_idx]}"

    def _on_next_backup_time(self):
        if not self._backup_times_list:
            return
        self._selected_backup_idx = min(len(self._backup_times_list) - 1, self._selected_backup_idx + 1)
        self._restore_time_label.text = f"Backup Time: {self._backup_times_list[self._selected_backup_idx]}"

    def _on_load_entities_for_restore(self):
        if not self._backup_times_list:
            self._set_status("[INFO] Load backup times first.")
            return
        try:
            bt = self._backup_times_list[self._selected_backup_idx]
            encoded_bt = urllib.request.quote(bt, safe="")
            result = self._api_get(f"api/v1/entities/list?backup_time={encoded_bt}")
            self._restore_entities_list = result.get("entities", [])
            self._selected_entity_idx = 0
            if self._restore_entities_list:
                ep = self._restore_entities_list[0].get("entity_path", "?")
                self._restore_entity_label.text = f"Entity: {ep}"
                self._set_status(f"[OK] Loaded {len(self._restore_entities_list)} entity(s) at {bt}.")
            else:
                self._restore_entity_label.text = "Entity: (none found)"
                self._set_status(f"[INFO] No entities at backup time {bt}.")
        except Exception as e:
            self._set_status(f"[FAIL] Load entities error: {e}")

    def _on_prev_entity(self):
        if not self._restore_entities_list:
            return
        self._selected_entity_idx = max(0, self._selected_entity_idx - 1)
        ep = self._restore_entities_list[self._selected_entity_idx].get("entity_path", "?")
        self._restore_entity_label.text = f"Entity: {ep}"

    def _on_next_entity(self):
        if not self._restore_entities_list:
            return
        self._selected_entity_idx = min(len(self._restore_entities_list) - 1, self._selected_entity_idx + 1)
        ep = self._restore_entities_list[self._selected_entity_idx].get("entity_path", "?")
        self._restore_entity_label.text = f"Entity: {ep}"

    def _on_restore_entity(self):
        """Restore an entity from backup: fetch data → remove current → re-add from USD."""
        if not self._backup_times_list or not self._restore_entities_list:
            self._set_status("[INFO] Load backup times and entities first.")
            return
        try:
            bt = self._backup_times_list[self._selected_backup_idx]
            entity_data = self._restore_entities_list[self._selected_entity_idx]
            entity_path = entity_data.get("entity_path", "")
            usd_file_path = entity_data.get("usd_file_path", "")

            if not entity_path:
                self._set_status("[FAIL] No entity path selected.")
                return

            stage = omni.usd.get_context().get_stage()
            if not stage:
                self._set_status("[FAIL] No active Stage.")
                return

            # Remove existing prim at entity_path
            existing = stage.GetPrimAtPath(entity_path)
            if existing.IsValid():
                stage.RemovePrim(entity_path)

            # Fetch restore data from API (entity info + prim snapshots)
            encoded_ep = urllib.request.quote(entity_path.lstrip("/"), safe="/")
            encoded_bt = urllib.request.quote(bt, safe="")
            result = self._api_get(
                f"api/v1/entities/{encoded_ep}/restore?backup_time={encoded_bt}"
            )

            entity_info = result.get("entity", {})
            prim_snapshots = result.get("prim_snapshots", [])
            usd_path = entity_info.get("usd_file_path", "")

            # Strategy: Level 3 (USD binary) → Level 2 (source ref + property overrides) → Level 1 (prim snapshots)
            restore_method = "unknown"

            if usd_path and usd_path.startswith("s3://"):
                # Level 3: Download USD from MinIO and add as local reference
                try:
                    local_usd = self._download_usd_from_minio(usd_path)
                    if local_usd:
                        prim = stage.DefinePrim(entity_path)
                        prim.GetReferences().AddReference(local_usd)
                        restore_method = "Level 3 (USD binary from MinIO)"
                except Exception as dl_exc:
                    self._set_status(
                        f"[WARN] Level 3 USD download failed: {dl_exc}\n"
                        f"Falling back to Level 2 restore..."
                    )
                    restore_method = None  # fall through to Level 2

            if restore_method == "unknown":
                restore_method = None

            if restore_method is None:
                source_asset = entity_info.get("source_asset", "")
                if source_asset:
                    # Level 2: Restore from original Nucleus reference
                    prim = stage.DefinePrim(entity_path)
                    prim.GetReferences().AddReference(source_asset)
                    restore_method = f"Level 2 (source reference: {source_asset})"
                else:
                    # Level 1: Recreate structure from prim snapshots
                    for snap in prim_snapshots:
                        rel_path = snap.get("relative_path", "/")
                        prim_type = snap.get("prim_type", "Xform")
                        full_path = entity_path + rel_path if rel_path != "/" else entity_path
                        stage.DefinePrim(full_path, prim_type)
                    restore_method = f"Level 1 (prim snapshots: {len(prim_snapshots)} prims)"

            # Apply property overrides from prim snapshots (restores transforms, visibility, etc.)
            overrides_applied = self._apply_property_overrides(stage, entity_path, prim_snapshots)

            self._set_status(
                f"[OK] Restored entity '{entity_path}':\n"
                f"  Method: {restore_method}\n"
                f"  Backup time: {bt}\n"
                f"  Sub-prims: {len(prim_snapshots)}, Overrides applied: {overrides_applied}"
            )
        except Exception as e:
            self._set_status(f"[FAIL] Restore error:\n{traceback.format_exc()}")

    # =========================================================================
    #  Sample IoT Data Generation
    # =========================================================================

    def _create_sample_iot_frame(self):
        frame = CollapsableFrame("Dynamic IoT Test", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Generate sample IoT data for Dynamic entities.\n"
                    "Inserts random pos/speed/timestamp records into Iceberg.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._iot_entity_field = StringField(
                    "Entity Path",
                    default_value="/World/Robots/Jetbot",
                    tooltip="Entity path for sample IoT data",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._iot_entity_field)

                self._iot_count_field = StringField(
                    "Record Count",
                    default_value="10",
                    tooltip="Number of sample IoT records to generate",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._iot_count_field)

                btn = Button(
                    "Generate Sample IoT Data",
                    "GENERATE IOT",
                    tooltip="Send random IoT data to Lakehouse API",
                    on_click_fn=self._on_generate_sample_iot,
                )
                self.wrapped_ui_elements.append(btn)

    def _on_generate_sample_iot(self):
        try:
            entity_path = self._iot_entity_field.get_value()
            count_str = self._iot_count_field.get_value()
            try:
                count = int(count_str)
            except ValueError:
                count = 10

            payload = {
                "entity_path": entity_path,
                "count": count,
            }
            result = self._api_post_json("api/v1/dynamic/sample-ingest", payload)
            self._set_status(
                f"[OK] Sample IoT data generated.\n"
                f"Entity: {entity_path}\n"
                f"Records: {result.get('records_generated', 0)}\n"
                f"Table: {result.get('table_name', 'N/A')}"
            )
        except Exception as e:
            self._set_status(f"[FAIL] Sample IoT error:\n{traceback.format_exc()}")

    # =========================================================================
    #  HTTP Helpers (urllib — stdlib only)
    # =========================================================================

    def _api_get(self, endpoint: str) -> dict:
        url = f"{self._get_api_url()}/{endpoint}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _api_post_json(self, endpoint: str, data: dict) -> dict:
        url = f"{self._get_api_url()}/{endpoint}"
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _api_post_file(self, endpoint: str, file_path: str, fields: dict = None) -> dict:
        """Upload a file via multipart/form-data."""
        boundary = uuid.uuid4().hex
        body = b""

        if fields:
            for key, value in fields.items():
                body += f"--{boundary}\r\n".encode()
                body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                body += f"{value}\r\n".encode()

        filename = os.path.basename(file_path)
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        with open(file_path, "rb") as f:
            body += f.read()
        body += b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        url = f"{self._get_api_url()}/{endpoint}"
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
