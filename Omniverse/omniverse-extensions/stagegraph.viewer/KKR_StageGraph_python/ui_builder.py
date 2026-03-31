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

import asyncio
import json
import os
import traceback
import urllib.error
import urllib.request

import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .data_fetcher import StaticPrimFetcher, PrimRecord

# API middleware URL (env-var-driven for Docker/k8s portability).
DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")


# =============================================================================
#  TreeView support classes (omni.ui.AbstractItemModel pattern)
# =============================================================================


class StageTreeItem(ui.AbstractItem):
    """A single node in the stage hierarchy tree."""

    def __init__(self, prim_path: str, prim_name: str, prim_type: str):
        super().__init__()
        self.prim_path = prim_path
        self.prim_name = prim_name
        self.prim_type = prim_type
        self.children: list["StageTreeItem"] = []
        self.name_model = ui.SimpleStringModel(prim_name)
        self.type_model = ui.SimpleStringModel(prim_type)


class StageTreeModel(ui.AbstractItemModel):
    """Item model that backs the stage hierarchy TreeView."""

    def __init__(self, roots: list[StageTreeItem]):
        super().__init__()
        self._roots = roots

    def get_item_children(self, item):
        if item is None:
            return self._roots
        return item.children

    def get_item_value_model_count(self, item):
        return 2  # column 0 = name, column 1 = type

    def get_item_value_model(self, item, column_id):
        if column_id == 0:
            return item.name_model
        return item.type_model


class StageTreeDelegate(ui.AbstractItemDelegate):
    """Custom delegate that draws colored type indicators next to prim names."""

    def __init__(self, color_fn):
        super().__init__()
        self._color_fn = color_fn

    def build_branch(self, model, item, column_id, level, expanded):
        """Draw the expand/collapse arrow area."""
        if column_id == 0:
            with ui.HStack(width=16 * (level + 1), height=20):
                if item.children:
                    ui.Label(
                        "v " if expanded else "> ",
                        width=16,
                        style={"color": 0xFFCCCCCC, "font_size": 12},
                    )
                else:
                    ui.Spacer(width=16)

    def build_widget(self, model, item, column_id, level, expanded):
        """Draw the content for each cell."""
        if column_id == 0:
            color = self._color_fn(item.prim_type)
            with ui.HStack(height=20, spacing=4):
                ui.Rectangle(
                    width=12, height=12,
                    style={"background_color": color, "border_radius": 2},
                )
                ui.Label(
                    item.prim_name,
                    style={"color": 0xFFEEEEEE, "font_size": 13},
                )
        elif column_id == 1:
            with ui.HStack(height=20):
                ui.Label(
                    item.prim_type,
                    width=100,
                    style={"color": 0xFF999999, "font_size": 11},
                )


# =============================================================================
#  UIBuilder
# =============================================================================


class UIBuilder:
    """Main UI builder for the StageGraph Viewer extension."""

    # Type color mapping (omni.ui uses 0xAABBGGRR format)
    TYPE_COLORS = {
        "Mesh": 0xFFFF8844,         # Blue (BGR)
        "Xform": 0xFF888888,        # Gray
        "Scope": 0xFFCC88FF,        # Purple
        "DistantLight": 0xFF00CCFF, # Yellow
        "DomeLight": 0xFF00CCFF,
        "SphereLight": 0xFF00CCFF,
        "Camera": 0xFF44FF44,       # Green
        "Material": 0xFFFF44FF,     # Magenta
        "Shader": 0xFFFF44FF,
    }
    DEFAULT_COLOR = 0xFFAAAAAA      # Light gray

    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        self._fetcher = StaticPrimFetcher()
        self._tree_model = None
        self._tree_delegate = None
        self._tree_view = None
        self._tree_container = None
        self._stats_container = None
        self._diff_container = None

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
        """Refresh tree on stage open/close."""
        if hasattr(self, "_tree_container") and self._tree_container is not None:
            try:
                self._refresh_tree()
            except Exception as e:
                print(f"[KKR.StageGraph] Stage event error: {e}")

    def cleanup(self):
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()

    def build_ui(self):
        self._create_status_frame()
        self._create_api_config_frame()
        self._create_tree_frame()
        self._create_type_stats_frame()
        self._create_iceberg_diff_frame()

    # =========================================================================
    #  Status Log
    # =========================================================================

    def _create_status_frame(self):
        self._status_frame = CollapsableFrame("Status / Log", collapsed=False)
        with self._status_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._status_field = TextBlock(
                    "Last Operation",
                    num_lines=8,
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
        self._set_status("Checking API connection...")
        asyncio.ensure_future(self._async_health_check())

    async def _async_health_check(self):
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self._api_get("api/v1/health"))
            self._set_status(f"[OK] API connected: {result}")
        except Exception as e:
            self._set_status(f"[FAIL] Cannot connect to API: {e}")

    # =========================================================================
    #  Stage Hierarchy TreeView
    # =========================================================================

    def _create_tree_frame(self):
        frame = CollapsableFrame("Stage Hierarchy", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Live USD Stage hierarchy. Click a row to select the prim in the viewport.\n"
                    "Colored indicators show the prim type.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                btn = Button(
                    "Refresh Tree",
                    "REFRESH",
                    tooltip="Re-scan the current USD Stage and rebuild the tree",
                    on_click_fn=self._refresh_tree,
                )
                self.wrapped_ui_elements.append(btn)

                # Container that holds the TreeView (rebuilt on refresh)
                self._tree_container = ui.VStack(spacing=2, height=0)
                with self._tree_container:
                    ui.Label(
                        "Press 'REFRESH' to scan the stage.",
                        style={"color": 0xFF999999},
                    )

    def _refresh_tree(self):
        """Scan the stage and rebuild the TreeView."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            self._tree_container.clear()
            with self._tree_container:
                ui.Label("No Stage open.", style={"color": 0xFF6666FF})
            self._set_status("[WARN] No Stage is currently open.")
            return

        try:
            roots = self._scan_stage_hierarchy(stage)
            total = self._count_tree_items(roots)
            self._tree_model = StageTreeModel(roots)
            self._tree_delegate = StageTreeDelegate(self._get_type_color)

            self._tree_container.clear()
            with self._tree_container:
                self._tree_view = ui.TreeView(
                    self._tree_model,
                    delegate=self._tree_delegate,
                    root_visible=False,
                    header_visible=False,
                    columns_resizable=True,
                    column_widths=[ui.Fraction(3), ui.Fraction(1)],
                    height=ui.Pixel(min(total * 22 + 10, 500)),
                    style={"TreeView": {"background_color": 0xFF1A1A1A}},
                )
                self._tree_view.set_selection_changed_fn(self._on_tree_selection_changed)

            self._set_status(f"[OK] Stage scanned: {total} prims found.")

            # Also refresh type stats if the container exists
            if self._stats_container is not None:
                self._refresh_type_stats(stage)

        except Exception as exc:
            self._set_status(f"[FAIL] Tree refresh error:\n{traceback.format_exc()}")

    def _on_tree_selection_changed(self, selection):
        """When a tree row is selected, select the prim in the viewport."""
        if not selection:
            return
        item = selection[0]
        if hasattr(item, "prim_path") and item.prim_path:
            try:
                omni.usd.get_context().get_selection().set_selected_prim_paths(
                    [item.prim_path], True
                )
                self._set_status(f"Selected: {item.prim_path} ({item.prim_type})")
            except Exception as exc:
                self._set_status(f"[WARN] Could not select prim: {exc}")

    def _scan_stage_hierarchy(self, stage) -> list[StageTreeItem]:
        """Traverse the stage and build a tree of StageTreeItems."""
        root_prim = stage.GetPseudoRoot()
        roots: list[StageTreeItem] = []
        for child in root_prim.GetChildren():
            item = self._build_tree_item(child)
            roots.append(item)
        return roots

    def _build_tree_item(self, prim, depth: int = 0, max_depth: int = 50) -> StageTreeItem:
        """Recursively build a StageTreeItem from a USD Prim."""
        path = str(prim.GetPath())
        name = prim.GetName()
        prim_type = prim.GetTypeName() or "Unknown"
        item = StageTreeItem(path, name, prim_type)
        if depth < max_depth:
            for child in prim.GetChildren():
                item.children.append(self._build_tree_item(child, depth + 1, max_depth))
        return item

    def _count_tree_items(self, items: list[StageTreeItem]) -> int:
        """Count total items in the tree (for sizing)."""
        count = len(items)
        for item in items:
            count += self._count_tree_items(item.children)
        return count

    # =========================================================================
    #  Type Distribution Stats
    # =========================================================================

    def _create_type_stats_frame(self):
        frame = CollapsableFrame("Type Distribution", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Proportional bars showing prim type counts from the current stage.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )
                self._stats_container = ui.VStack(spacing=2, height=0)
                with self._stats_container:
                    ui.Label(
                        "Refresh the Stage Hierarchy tree to populate.",
                        style={"color": 0xFF999999},
                    )

    def _refresh_type_stats(self, stage):
        """Rebuild type distribution bars from the current stage."""
        type_counts: dict[str, int] = {}
        for prim in stage.Traverse():
            t = prim.GetTypeName() or "Unknown"
            type_counts[t] = type_counts.get(t, 0) + 1

        total = sum(type_counts.values())
        if total == 0:
            return

        # Sort by count descending
        sorted_types = sorted(type_counts.items(), key=lambda kv: -kv[1])
        max_count = sorted_types[0][1] if sorted_types else 1

        self._stats_container.clear()
        with self._stats_container:
            for type_name, count in sorted_types:
                color = self._get_type_color(type_name)
                fraction = count / max_count
                with ui.HStack(height=22, spacing=4):
                    ui.Rectangle(
                        width=ui.Pixel(int(fraction * 250)),
                        height=18,
                        style={
                            "background_color": color,
                            "border_radius": 3,
                        },
                    )
                    ui.Label(
                        f"{type_name}: {count}",
                        style={"color": 0xFFDDDDDD, "font_size": 12},
                    )

    # =========================================================================
    #  Iceberg Diff
    # =========================================================================

    def _create_iceberg_diff_frame(self):
        frame = CollapsableFrame("Iceberg Diff", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Compare current USD Stage prims against the Iceberg Lakehouse catalog.\n"
                    "Green = stage only, Red = Iceberg only, White = both.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                btn = Button(
                    "Compare with Iceberg",
                    "DIFF",
                    tooltip="Fetch prims from Iceberg and diff against current stage",
                    on_click_fn=self._on_iceberg_diff,
                )
                self.wrapped_ui_elements.append(btn)

                self._diff_container = ui.VStack(spacing=2, height=0)
                with self._diff_container:
                    ui.Label(
                        "Press 'DIFF' to compare.",
                        style={"color": 0xFF999999},
                    )

    def _on_iceberg_diff(self):
        """Fetch Iceberg prims and diff against the live stage."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            self._set_status("[WARN] No Stage is currently open for diff.")
            return

        self._set_status("Fetching prims from Iceberg...")
        asyncio.ensure_future(self._async_iceberg_diff(stage))

    async def _async_iceberg_diff(self, stage):
        """Async worker: fetch Iceberg prims and render diff."""
        # Collect current stage prim paths
        stage_paths: set[str] = set()
        for prim in stage.Traverse():
            stage_paths.add(str(prim.GetPath()))

        # Fetch from Iceberg API
        iceberg_paths: set[str] = set()
        source = "api"
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: self._api_get("api/v1/static/prims?limit=5000")
            )
            records = result if isinstance(result, list) else result.get("data", result.get("prims", []))
            for r in records:
                path = r.get("prim_path", "")
                if path:
                    iceberg_paths.add(path)
        except Exception as exc:
            source = "demo"
            self._set_status(f"[WARN] API unreachable, using demo data: {exc}")
            for p in self._fetcher.generate_demo_prims():
                iceberg_paths.add(p.prim_path)

        # Compute diff sets
        stage_only = sorted(stage_paths - iceberg_paths)
        iceberg_only = sorted(iceberg_paths - stage_paths)
        both = sorted(stage_paths & iceberg_paths)

        total_stage = len(stage_paths)
        total_iceberg = len(iceberg_paths)
        self._set_status(
            f"[OK] Diff complete (source={source}):\n"
            f"  Stage: {total_stage} prims | Iceberg: {total_iceberg} prims\n"
            f"  Stage only: {len(stage_only)} | Iceberg only: {len(iceberg_only)} | Both: {len(both)}"
        )

        # Render diff list
        self._diff_container.clear()
        with self._diff_container:
            with ui.ScrollingFrame(height=ui.Pixel(min((len(stage_only) + len(iceberg_only) + len(both)) * 20 + 10, 400))):
                with ui.VStack(spacing=1):
                    # Stage only (green)
                    for path in stage_only:
                        ui.Label(
                            f"+ {path}",
                            style={"color": 0xFF44FF44, "font_size": 11},
                        )
                    # Iceberg only (red)
                    for path in iceberg_only:
                        ui.Label(
                            f"- {path}",
                            style={"color": 0xFF4444FF, "font_size": 11},
                        )
                    # Both (white)
                    for path in both:
                        ui.Label(
                            f"  {path}",
                            style={"color": 0xFFFFFFFF, "font_size": 11},
                        )

    # =========================================================================
    #  HTTP Helpers (stdlib only)
    # =========================================================================

    def _api_get(self, endpoint: str) -> dict:
        url = f"{self._get_api_url()}/{endpoint}"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # =========================================================================
    #  Utility
    # =========================================================================

    @classmethod
    def _get_type_color(cls, type_name: str) -> int:
        """Look up color for a prim type, with fallback."""
        return cls.TYPE_COLORS.get(type_name, cls.DEFAULT_COLOR)
