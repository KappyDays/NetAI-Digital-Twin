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

import json
import os
import traceback
import urllib.error
import urllib.request
import uuid

import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

# API middleware URL (env-var-driven for Docker/k8s portability).
# Isaac Sim container is connected to iceberg_net via "docker network connect",
# so it can resolve "lakehouse-api" by container name directly.
# k8s: same — Services in the same namespace resolve by name.
DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        # Navigation state: "summary", "drilldown", or "object_detail"
        self._nav_mode = "summary"
        self._current_space_id = None
        self._drilldown_cache = None  # Cached drill-down API response
        # Object detail state (third navigation level)
        self._selected_object_type = None   # "static" or "dynamic"
        self._selected_object_data = None   # Full object dict for detail panel
        self._selected_object_id = None     # Display identifier

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
        self._create_space_explorer_frame()
        self._create_iceberg_export_frame()
        self._create_s3_export_frame()

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
        try:
            result = self._api_get("api/v1/health")
            self._set_status(f"[OK] API connected: {result}")
        except Exception as e:
            self._set_status(f"[FAIL] Cannot connect to API: {e}")

    # =========================================================================
    #  [Space Explorer] Congestion Summary + Object Drill-Down
    # =========================================================================

    # Color constants (0xAARRGGBB in omni.ui convention → actually 0xAABBGGRR)
    _COLOR_GREEN = 0xFF00CC66   # 여유 (Low)
    _COLOR_YELLOW = 0xFF00CCFF  # 보통 (Medium) — BGR: FF CC 00 = Orange-Yellow
    _COLOR_RED = 0xFF3333FF     # 혼잡 (High) — BGR: FF 33 33 = Red
    _COLOR_GRAY = 0xFF888888    # No data
    _COLOR_CYAN = 0xFFFFCC00    # Dynamic object highlight (BGR: 00 CC FF = Cyan)
    _COLOR_WHITE = 0xFFFFFFFF
    _COLOR_DIM = 0xFFAAAAAA

    # Status icon mapping for dynamic objects
    _STATUS_ICONS = {
        "active": "[A]",   # Active — seen recently
        "idle": "[I]",     # Idle — not seen for 60-300s
        "stale": "[S]",    # Stale — not seen for >300s
        "unknown": "[?]",
    }
    _STATUS_COLORS = {
        "active": 0xFF00CC66,   # Green
        "idle": 0xFF00CCFF,     # Yellow
        "stale": 0xFF3333FF,    # Red
        "unknown": 0xFF888888,  # Gray
    }

    @staticmethod
    def _congestion_status(level: float) -> tuple:
        """Return (label, color) based on congestion_level (0.0–1.0)."""
        if level < 0.4:
            return "Low", UIBuilder._COLOR_GREEN
        elif level < 0.7:
            return "Medium", UIBuilder._COLOR_YELLOW
        else:
            return "High", UIBuilder._COLOR_RED

    def _create_space_explorer_frame(self):
        """Create the combined space summary + drill-down frame."""
        frame = CollapsableFrame("Space Explorer (Congestion + Drill-Down)", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Congestion overview with per-space drill-down.\n"
                    "Click a space row to view object-level details.\n"
                    "Colors: Green=Low | Yellow=Medium | Red=High",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                # Navigation breadcrumb bar
                self._nav_bar = ui.HStack(height=28, spacing=4)
                with self._nav_bar:
                    self._nav_label = ui.Label(
                        "All Spaces (Summary View)",
                        style={"color": 0xFF66CCFF, "font_size": 14},
                        width=ui.Fraction(4),
                    )

                # Main content container — switches between summary and drilldown
                self._explorer_container = ui.VStack(spacing=4, height=0)
                with self._explorer_container:
                    ui.Label(
                        "Press 'REFRESH' to load congestion data.",
                        style={"color": 0xFF999999},
                    )

                # Action buttons row
                with ui.HStack(height=30, spacing=4):
                    btn_refresh = Button(
                        "Refresh",
                        "REFRESH",
                        tooltip="Fetch latest congestion data from API",
                        on_click_fn=self._on_refresh_congestion,
                    )
                    self.wrapped_ui_elements.append(btn_refresh)

                    btn_back = Button(
                        "Back to Summary",
                        "BACK",
                        tooltip="Return to space summary view",
                        on_click_fn=self._on_navigate_back,
                    )
                    self.wrapped_ui_elements.append(btn_back)

    # ── Navigation Logic ──────────────────────────────────────────────

    def _navigate_to_drilldown(self, space_id: str):
        """Switch from summary view to drill-down view for a specific space."""
        self._nav_mode = "drilldown"
        self._current_space_id = space_id
        self._nav_label.text = f"Space: {space_id} (Drill-Down View)"

        self._set_status(f"Loading drill-down for space '{space_id}'...")

        try:
            # URL-encode the space_id for the API call
            encoded = urllib.request.quote(space_id, safe="")
            result = self._api_get(f"api/v1/static/spaces/{encoded}/drilldown")
            self._drilldown_cache = result
        except Exception as e:
            self._set_status(f"[FAIL] Drill-down API error: {e}")
            # Generate demo drill-down data for offline testing
            result = self._demo_drilldown_data(space_id)
            self._drilldown_cache = result

        self._render_drilldown_panel(result)

    def _navigate_to_object_detail(self, obj_type: str, obj_data: dict, obj_id: str):
        """Switch to object detail view (third navigation level).

        Args:
            obj_type: "static" or "dynamic"
            obj_data: Full object dict from drill-down cache
            obj_id: Human-readable identifier (prim_path or object_id)
        """
        self._nav_mode = "object_detail"
        self._selected_object_type = obj_type
        self._selected_object_data = obj_data
        self._selected_object_id = obj_id

        # Shorten display name for breadcrumb
        short_name = obj_id.rsplit("/", 1)[-1] if "/" in obj_id else obj_id
        self._nav_label.text = (
            f"Spaces > {self._current_space_id} > {short_name} (Detail)"
        )

        self._render_object_detail_panel(obj_type, obj_data)

    def _on_navigate_back(self):
        """Navigate back one level in the hierarchy.

        Levels: summary → drilldown → object_detail
        Back from object_detail → drilldown (re-render from cache)
        Back from drilldown → summary (re-fetch congestion)
        """
        if self._nav_mode == "object_detail":
            # Return to drill-down level
            self._nav_mode = "drilldown"
            self._selected_object_type = None
            self._selected_object_data = None
            self._selected_object_id = None
            self._nav_label.text = f"Space: {self._current_space_id} (Drill-Down View)"
            if self._drilldown_cache:
                self._render_drilldown_panel(self._drilldown_cache)
            else:
                self._navigate_to_drilldown(self._current_space_id)
        else:
            # Return to summary level
            self._nav_mode = "summary"
            self._current_space_id = None
            self._drilldown_cache = None
            self._selected_object_type = None
            self._selected_object_data = None
            self._selected_object_id = None
            self._nav_label.text = "All Spaces (Summary View)"
            # Re-fetch congestion data
            self._on_refresh_congestion()

    # ── Congestion Summary View ───────────────────────────────────────

    def _on_refresh_congestion(self):
        """Fetch congestion data from API and rebuild the panel."""
        # If in object_detail mode, go back to drilldown and refresh
        if self._nav_mode == "object_detail" and self._current_space_id:
            self._nav_mode = "drilldown"
            self._selected_object_type = None
            self._selected_object_data = None
            self._selected_object_id = None
            self._navigate_to_drilldown(self._current_space_id)
            return
        # If currently in drilldown mode and user clicks refresh, reload drilldown
        if self._nav_mode == "drilldown" and self._current_space_id:
            self._navigate_to_drilldown(self._current_space_id)
            return

        try:
            result = self._api_get("api/v1/congestion")
        except Exception as e:
            self._set_status(f"[FAIL] Congestion fetch error: {e}")
            result = self._demo_congestion_data()

        self._render_congestion_panel(result)

    @staticmethod
    def _demo_congestion_data() -> dict:
        """Generate demo data when API is not available."""
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        return {
            "spaces": [
                {"space_id": "Room_A", "object_count": 2, "congestion_level": 0.25, "timestamp": now},
                {"space_id": "Room_B", "object_count": 5, "congestion_level": 0.65, "timestamp": now},
                {"space_id": "Hallway_01", "object_count": 8, "congestion_level": 0.90, "timestamp": now},
            ],
            "total_objects": 15,
            "snapshot_time": now,
        }

    @staticmethod
    def _demo_drilldown_data(space_id: str) -> dict:
        """Generate demo drill-down data when API is not available."""
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        return {
            "space_id": space_id,
            "static_count": 5,
            "dynamic_count": 2,
            "type_distribution": {"Mesh": 3, "Xform": 1, "DistantLight": 1},
            "static_objects": [
                {
                    "prim_path": f"/World/{space_id}/Floor",
                    "object_type": "Mesh",
                    "parent_path": f"/World/{space_id}",
                    "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "visibility": "inherited",
                    "material_path": "/World/Looks/Floor_Mat",
                    "semantic_label": "floor",
                    "child_count": 0,
                    "depth": 1,
                    "properties_raw": "{}",
                },
                {
                    "prim_path": f"/World/{space_id}/Chair_01",
                    "object_type": "Mesh",
                    "parent_path": f"/World/{space_id}",
                    "position": {"x": 1.5, "y": 0.0, "z": 2.0},
                    "rotation": {"x": 0.0, "y": 45.0, "z": 0.0},
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "visibility": "inherited",
                    "material_path": None,
                    "semantic_label": "chair",
                    "child_count": 0,
                    "depth": 1,
                    "properties_raw": "{}",
                },
                {
                    "prim_path": f"/World/{space_id}/Table_01",
                    "object_type": "Mesh",
                    "parent_path": f"/World/{space_id}",
                    "position": {"x": 3.0, "y": 0.0, "z": 2.0},
                    "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                    "visibility": "inherited",
                    "material_path": "/World/Looks/Wood_Mat",
                    "semantic_label": "table",
                    "child_count": 2,
                    "depth": 1,
                    "properties_raw": "{}",
                },
                {
                    "prim_path": f"/World/{space_id}/Lights",
                    "object_type": "Xform",
                    "parent_path": f"/World/{space_id}",
                    "position": {"x": 0.0, "y": 3.0, "z": 0.0},
                    "rotation": None,
                    "scale": None,
                    "visibility": "inherited",
                    "material_path": None,
                    "semantic_label": None,
                    "child_count": 1,
                    "depth": 1,
                    "properties_raw": "{}",
                },
                {
                    "prim_path": f"/World/{space_id}/Lights/Ceiling_Light",
                    "object_type": "DistantLight",
                    "parent_path": f"/World/{space_id}/Lights",
                    "position": {"x": 0.0, "y": 3.0, "z": 0.0},
                    "rotation": None,
                    "scale": None,
                    "visibility": "inherited",
                    "material_path": None,
                    "semantic_label": None,
                    "child_count": 0,
                    "depth": 2,
                    "properties_raw": "{}",
                },
            ],
            "dynamic_objects": [
                {
                    "object_id": "robot_01",
                    "position": {"x": 2.1, "y": 0.0, "z": 1.5},
                    "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
                    "speed": 0.5,
                    "space_id": space_id,
                    "last_seen": now,
                    "status": "active",
                    "properties": "{}",
                },
                {
                    "object_id": "agv_03",
                    "position": {"x": 4.0, "y": 0.0, "z": 3.0},
                    "rotation": {"x": 0.0, "y": 180.0, "z": 0.0},
                    "speed": 0.0,
                    "space_id": space_id,
                    "last_seen": now,
                    "status": "idle",
                    "properties": "{}",
                },
            ],
            "last_static_ingestion": now,
            "snapshot_time": now,
        }

    def _render_congestion_panel(self, data: dict):
        """Rebuild the explorer container with congestion summary data.

        Renders a per-space congestion summary panel widget with:
        - Space name (공간명)
        - Congestion numeric value (혼잡도 수치, 0–100%)
        - Color indicator dot + progress bar (색상 인디케이터)
          Green (< 40%) | Yellow (40–70%) | Red (>= 70%)
        """
        spaces = data.get("spaces", [])
        total_objects = data.get("total_objects", 0)
        snapshot_time = data.get("snapshot_time", "N/A")

        self._explorer_container.clear()

        with self._explorer_container:
            # ══════════════════════════════════════════════════════════
            #  Overall Summary Statistics Bar
            # ══════════════════════════════════════════════════════════
            with ui.ZStack(height=48):
                ui.Rectangle(
                    style={"background_color": 0xFF1A1A2E, "border_radius": 6},
                )
                with ui.VStack(spacing=2, height=0):
                    ui.Spacer(height=4)
                    with ui.HStack(height=18, spacing=8):
                        ui.Spacer(width=8)
                        ui.Label(
                            f"Spaces: {len(spaces)}",
                            style={"color": 0xFF66CCFF, "font_size": 13},
                            width=ui.Fraction(1),
                        )
                        ui.Label(
                            f"Total Objects: {total_objects}",
                            style={"color": self._COLOR_WHITE, "font_size": 13},
                            width=ui.Fraction(1),
                        )
                        # Overall congestion indicator
                        if spaces:
                            avg_level = sum(
                                sp.get("congestion_level", 0.0) for sp in spaces
                            ) / len(spaces)
                            avg_label, avg_color = self._congestion_status(avg_level)
                            ui.Label(
                                f"Avg: {avg_level * 100:.0f}% ({avg_label})",
                                style={"color": avg_color, "font_size": 13},
                                width=ui.Fraction(1),
                            )
                        else:
                            ui.Label(
                                "Avg: N/A",
                                style={"color": self._COLOR_GRAY, "font_size": 13},
                                width=ui.Fraction(1),
                            )
                    with ui.HStack(height=16, spacing=8):
                        ui.Spacer(width=8)
                        ui.Label(
                            f"Snapshot: {str(snapshot_time)[:19]}",
                            style={"color": self._COLOR_DIM, "font_size": 11},
                        )

            ui.Spacer(height=4)

            if not spaces:
                ui.Label(
                    "No space congestion data available.",
                    style={"color": 0xFFAAAA55},
                )
            else:
                # ══════════════════════════════════════════════════════
                #  Column Headers
                # ══════════════════════════════════════════════════════
                with ui.HStack(height=22, spacing=4):
                    ui.Label("", width=14)  # color dot placeholder
                    ui.Label("Space (click to drill-down)", width=ui.Fraction(3),
                             style={"color": 0xFFDDDDDD, "font_size": 12})
                    ui.Label("Obj", width=ui.Fraction(1),
                             alignment=ui.Alignment.CENTER,
                             style={"color": 0xFFDDDDDD, "font_size": 12})
                    ui.Label("Level", width=ui.Fraction(1),
                             alignment=ui.Alignment.CENTER,
                             style={"color": 0xFFDDDDDD, "font_size": 12})
                    ui.Label("Status", width=ui.Fraction(1),
                             alignment=ui.Alignment.CENTER,
                             style={"color": 0xFFDDDDDD, "font_size": 12})
                    ui.Label("Congestion Bar", width=ui.Fraction(2),
                             alignment=ui.Alignment.CENTER,
                             style={"color": 0xFFDDDDDD, "font_size": 12})

                # ══════════════════════════════════════════════════════
                #  Per-Space Congestion Rows
                # ══════════════════════════════════════════════════════
                for sp in spaces:
                    space_id = sp.get("space_id", "?")
                    obj_count = sp.get("object_count", 0)
                    level = sp.get("congestion_level", 0.0)
                    label, color = self._congestion_status(level)

                    # Wrap row in a ZStack so background rect can receive click
                    with ui.ZStack(height=30):
                        # Clickable background
                        bg_rect = ui.Rectangle(
                            style={
                                "background_color": 0xFF222222,
                                "border_radius": 4,
                                ":hovered": {"background_color": 0xFF333344},
                            },
                        )
                        # Bind click — capture space_id in closure
                        _sid = space_id  # capture
                        bg_rect.set_mouse_pressed_fn(
                            lambda x, y, btn, mod, sid=_sid: self._navigate_to_drilldown(sid)
                        )

                        with ui.HStack(height=28, spacing=4):
                            ui.Spacer(width=2)
                            # ── Color indicator dot (rounded rect as circle) ──
                            with ui.ZStack(width=14, height=28):
                                ui.Spacer(height=7)
                                ui.Rectangle(
                                    width=14,
                                    height=14,
                                    style={"background_color": color, "border_radius": 7},
                                )
                                ui.Spacer(height=7)
                            # ── Space name (clickable hint with arrow) ──
                            ui.Label(
                                f" > {space_id}",
                                width=ui.Fraction(3),
                                style={"color": 0xFF66CCFF, "font_size": 13},
                            )
                            # ── Object count ──
                            ui.Label(
                                str(obj_count),
                                width=ui.Fraction(1),
                                alignment=ui.Alignment.CENTER,
                                style={"color": self._COLOR_WHITE, "font_size": 13},
                            )
                            # ── Congestion percentage ──
                            ui.Label(
                                f"{level * 100:.0f}%",
                                width=ui.Fraction(1),
                                alignment=ui.Alignment.CENTER,
                                style={"color": color, "font_size": 14},
                            )
                            # ── Status label (Low/Medium/High) ──
                            ui.Label(
                                label,
                                width=ui.Fraction(1),
                                alignment=ui.Alignment.CENTER,
                                style={"color": color, "font_size": 13},
                            )
                            # ── Congestion bar (visual progress) ──
                            with ui.ZStack(width=ui.Fraction(2), height=18):
                                ui.Rectangle(
                                    style={"background_color": 0xFF333333, "border_radius": 3},
                                )
                                with ui.HStack(spacing=0):
                                    bar_frac = max(level, 0.02)
                                    ui.Rectangle(
                                        width=ui.Fraction(int(bar_frac * 100)),
                                        style={"background_color": color, "border_radius": 3},
                                    )
                                    ui.Spacer(width=ui.Fraction(int((1.0 - bar_frac) * 100)))

                # ══════════════════════════════════════════════════════
                #  Legend
                # ══════════════════════════════════════════════════════
                ui.Spacer(height=4)
                with ui.HStack(height=18, spacing=12):
                    for lbl, clr in [
                        ("Low (< 40%)", self._COLOR_GREEN),
                        ("Medium (40-70%)", self._COLOR_YELLOW),
                        ("High (>= 70%)", self._COLOR_RED),
                    ]:
                        with ui.HStack(spacing=4, width=ui.Fraction(1)):
                            with ui.ZStack(width=10, height=18):
                                ui.Spacer(height=4)
                                ui.Rectangle(
                                    width=10,
                                    height=10,
                                    style={"background_color": clr, "border_radius": 5},
                                )
                                ui.Spacer(height=4)
                            ui.Label(
                                lbl,
                                style={"color": self._COLOR_DIM, "font_size": 11},
                            )

        self._set_status(
            f"[OK] Congestion data loaded: {len(spaces)} spaces, "
            f"{total_objects} total objects. Click a space to drill down."
        )

    # ── Drill-Down View ───────────────────────────────────────────────

    def _render_drilldown_panel(self, data: dict):
        """Render the object-level drill-down for a single space."""
        space_id = data.get("space_id", "?")
        static_count = data.get("static_count", 0)
        dynamic_count = data.get("dynamic_count", 0)
        type_dist = data.get("type_distribution", {})
        static_objects = data.get("static_objects", [])
        dynamic_objects = data.get("dynamic_objects", [])
        last_ingestion = data.get("last_static_ingestion", "N/A")
        snapshot = data.get("snapshot_time", "N/A")

        self._explorer_container.clear()

        with self._explorer_container:
            # ── Summary Header ──
            with ui.VStack(spacing=3, height=0):
                ui.Label(
                    f"Space: {space_id}",
                    style={"color": 0xFF66CCFF, "font_size": 16},
                )
                with ui.HStack(height=20, spacing=8):
                    ui.Label(
                        f"Static: {static_count}",
                        style={"color": self._COLOR_DIM, "font_size": 12},
                        width=ui.Fraction(1),
                    )
                    ui.Label(
                        f"Dynamic: {dynamic_count}",
                        style={"color": self._COLOR_CYAN, "font_size": 12},
                        width=ui.Fraction(1),
                    )
                    ui.Label(
                        f"Snapshot: {str(snapshot)[:19]}",
                        style={"color": self._COLOR_DIM, "font_size": 12},
                        width=ui.Fraction(2),
                    )

                # Type distribution mini-chart
                if type_dist:
                    with ui.HStack(height=20, spacing=4):
                        ui.Label(
                            "Types: ",
                            style={"color": self._COLOR_DIM, "font_size": 12},
                            width=50,
                        )
                        type_str = " | ".join(
                            f"{t}: {c}" for t, c in sorted(type_dist.items(), key=lambda x: -x[1])
                        )
                        ui.Label(
                            type_str,
                            style={"color": self._COLOR_WHITE, "font_size": 12},
                            word_wrap=True,
                        )

            ui.Spacer(height=6)

            # ═══════════════════════════════════════════════════════════
            #  Dynamic Objects Section (IoT / Tracked)
            # ═══════════════════════════════════════════════════════════
            if dynamic_objects:
                ui.Label(
                    f"Dynamic Objects ({len(dynamic_objects)})",
                    style={"color": self._COLOR_CYAN, "font_size": 14},
                )
                ui.Spacer(height=2)

                # Column headers
                with ui.HStack(height=20, spacing=4):
                    ui.Label("Status", width=40,
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Object ID", width=ui.Fraction(2),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Position (X, Y, Z)", width=ui.Fraction(3),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Speed", width=ui.Fraction(1),
                             alignment=ui.Alignment.CENTER,
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Last Seen", width=ui.Fraction(2),
                             style={"color": self._COLOR_DIM, "font_size": 11})

                for dobj in dynamic_objects:
                    obj_id = dobj.get("object_id", "?")
                    pos = dobj.get("position", {})
                    rot = dobj.get("rotation", {})
                    speed = dobj.get("speed", 0.0)
                    status = dobj.get("status", "unknown")
                    last_seen = dobj.get("last_seen", "N/A")
                    status_icon = self._STATUS_ICONS.get(status, "[?]")
                    status_color = self._STATUS_COLORS.get(status, self._COLOR_GRAY)

                    # Clickable row with hover effect
                    with ui.ZStack(height=26):
                        dyn_bg = ui.Rectangle(
                            style={
                                "background_color": 0xFF1A1A2A,
                                "border_radius": 3,
                                ":hovered": {"background_color": 0xFF2A2A44},
                            },
                        )
                        # Capture object data for click handler
                        _dobj = dobj
                        _oid = obj_id
                        dyn_bg.set_mouse_pressed_fn(
                            lambda x, y, btn, mod, d=_dobj, oid=_oid: (
                                self._navigate_to_object_detail("dynamic", d, oid)
                            )
                        )

                        with ui.HStack(height=24, spacing=4):
                            ui.Label(
                                status_icon,
                                width=40,
                                alignment=ui.Alignment.CENTER,
                                style={"color": status_color, "font_size": 13},
                            )
                            ui.Label(
                                f"  {obj_id}",
                                width=ui.Fraction(2),
                                style={"color": self._COLOR_CYAN, "font_size": 12},
                                tooltip="Click to view object details",
                            )
                            pos_str = (
                                f"({pos.get('x', 0):.1f}, "
                                f"{pos.get('y', 0):.1f}, "
                                f"{pos.get('z', 0):.1f})"
                            )
                            ui.Label(
                                pos_str,
                                width=ui.Fraction(3),
                                style={"color": self._COLOR_WHITE, "font_size": 12},
                            )
                            ui.Label(
                                f"{speed:.1f} m/s",
                                width=ui.Fraction(1),
                                alignment=ui.Alignment.CENTER,
                                style={"color": self._COLOR_WHITE, "font_size": 12},
                            )
                            ui.Label(
                                str(last_seen)[:19] if last_seen else "N/A",
                                width=ui.Fraction(2),
                                style={"color": self._COLOR_DIM, "font_size": 11},
                            )

                ui.Spacer(height=6)

            # ═══════════════════════════════════════════════════════════
            #  Static Objects Section (Scene Graph Prims)
            # ═══════════════════════════════════════════════════════════
            ui.Label(
                f"Static Objects ({len(static_objects)})",
                style={"color": self._COLOR_WHITE, "font_size": 14},
            )
            ui.Spacer(height=2)

            if not static_objects:
                ui.Label(
                    "No static objects found in this space.",
                    style={"color": self._COLOR_DIM},
                )
            else:
                # Column headers for static objects
                with ui.HStack(height=20, spacing=4):
                    ui.Label("D", width=20,
                             tooltip="Hierarchy depth",
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Prim Path", width=ui.Fraction(3),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Type", width=ui.Fraction(1),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Position (X, Y, Z)", width=ui.Fraction(2),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Label", width=ui.Fraction(1),
                             style={"color": self._COLOR_DIM, "font_size": 11})
                    ui.Label("Ch", width=30,
                             tooltip="Child count",
                             alignment=ui.Alignment.CENTER,
                             style={"color": self._COLOR_DIM, "font_size": 11})

                # Render up to 200 objects to avoid UI slowdown
                display_limit = 200
                for i, sobj in enumerate(static_objects[:display_limit]):
                    prim_path = sobj.get("prim_path", "?")
                    obj_type = sobj.get("object_type", "?")
                    pos = sobj.get("position")
                    depth = sobj.get("depth", 0)
                    label = sobj.get("semantic_label", "")
                    child_count = sobj.get("child_count", 0)

                    # Indent based on depth for visual hierarchy
                    indent = "  " * min(depth, 4)
                    # Show only the last path segment for readability
                    short_path = prim_path.rsplit("/", 1)[-1] if "/" in prim_path else prim_path
                    display_name = f"{indent}{short_path}"

                    # Alternate row colors with hover highlight
                    row_bg = 0xFF1A1A1A if i % 2 == 0 else 0xFF222222

                    with ui.ZStack(height=22):
                        static_bg = ui.Rectangle(
                            style={
                                "background_color": row_bg,
                                "border_radius": 2,
                                ":hovered": {"background_color": 0xFF2A3333},
                            },
                        )
                        # Capture object data for click handler
                        _sobj = sobj
                        _pp = prim_path
                        static_bg.set_mouse_pressed_fn(
                            lambda x, y, btn, mod, d=_sobj, pp=_pp: (
                                self._navigate_to_object_detail("static", d, pp)
                            )
                        )

                        with ui.HStack(height=22, spacing=4):
                            ui.Label(
                                str(depth),
                                width=20,
                                alignment=ui.Alignment.CENTER,
                                style={"color": self._COLOR_DIM, "font_size": 11},
                            )
                            ui.Label(
                                display_name,
                                width=ui.Fraction(3),
                                tooltip=f"{prim_path} (click for details)",
                                style={"color": self._COLOR_WHITE, "font_size": 12},
                            )
                            ui.Label(
                                obj_type,
                                width=ui.Fraction(1),
                                style={"color": 0xFF88AACC, "font_size": 12},
                            )
                            if pos:
                                pos_str = (
                                    f"({pos.get('x', 0):.1f}, "
                                    f"{pos.get('y', 0):.1f}, "
                                    f"{pos.get('z', 0):.1f})"
                                )
                            else:
                                pos_str = "(N/A)"
                            ui.Label(
                                pos_str,
                                width=ui.Fraction(2),
                                style={"color": self._COLOR_DIM, "font_size": 12},
                            )
                            ui.Label(
                                label or "-",
                                width=ui.Fraction(1),
                                style={"color": 0xFF88CC88 if label else self._COLOR_DIM, "font_size": 12},
                            )
                            ui.Label(
                                str(child_count) if child_count > 0 else "-",
                                width=30,
                                alignment=ui.Alignment.CENTER,
                                style={"color": self._COLOR_DIM, "font_size": 11},
                            )

                if len(static_objects) > display_limit:
                    ui.Label(
                        f"... and {len(static_objects) - display_limit} more objects "
                        f"(showing first {display_limit})",
                        style={"color": self._COLOR_DIM, "font_size": 11},
                    )

            # ── Footer ──
            ui.Spacer(height=4)
            with ui.HStack(height=18, spacing=4):
                ui.Label(
                    f"Last ingestion: {str(last_ingestion)[:19] if last_ingestion else 'N/A'}",
                    style={"color": self._COLOR_DIM, "font_size": 11},
                )

        self._set_status(
            f"[OK] Drill-down loaded: {space_id} — "
            f"{static_count} static + {dynamic_count} dynamic objects. "
            f"Click any object row for details."
        )

    # ── Object Detail View (Third Level) ─────────────────────────────

    # Property label colors by category for visual grouping
    _DETAIL_SECTION_COLORS = {
        "identity": 0xFF66CCFF,     # Cyan — identity fields
        "transform": 0xFF88FF88,    # Green — spatial/transform fields
        "visual": 0xFFFFCC66,       # Gold — visual/material fields
        "hierarchy": 0xFFCC88FF,    # Purple — hierarchy fields
        "iot": 0xFF66FFCC,          # Teal — IoT/sensor fields
        "meta": 0xFFAAAACC,         # Muted lavender — metadata
    }

    def _render_object_detail_panel(self, obj_type: str, data: dict):
        """Render a full detail panel for a single object.

        Supports both static (USD Prim) and dynamic (IoT) object types.
        Shows all available properties in categorized sections.
        """
        self._explorer_container.clear()

        with self._explorer_container:
            if obj_type == "static":
                self._render_static_object_detail(data)
            elif obj_type == "dynamic":
                self._render_dynamic_object_detail(data)
            else:
                ui.Label(
                    f"Unknown object type: {obj_type}",
                    style={"color": self._COLOR_RED},
                )

    def _render_static_object_detail(self, data: dict):
        """Render detail panel for a static USD Prim object."""
        prim_path = data.get("prim_path", "?")
        obj_type = data.get("object_type", "?")
        parent_path = data.get("parent_path", "")
        pos = data.get("position")
        rot = data.get("rotation")
        scale = data.get("scale")
        visibility = data.get("visibility", "N/A")
        material = data.get("material_path")
        sem_label = data.get("semantic_label")
        child_count = data.get("child_count", 0)
        depth = data.get("depth", 0)
        props_raw = data.get("properties_raw", "{}")

        # ── Header ──
        short_name = prim_path.rsplit("/", 1)[-1] if "/" in prim_path else prim_path
        with ui.VStack(spacing=2, height=0):
            ui.Label(
                f"Static Object: {short_name}",
                style={"color": self._DETAIL_SECTION_COLORS["identity"], "font_size": 16},
            )
            ui.Label(
                f"Type: {obj_type}",
                style={"color": 0xFF88AACC, "font_size": 13},
            )
            ui.Spacer(height=4)

        # ── Identity Section ──
        self._detail_section_header("Identity", "identity")
        self._detail_kv_row("Prim Path", prim_path, "identity")
        self._detail_kv_row("Parent Path", parent_path or "(root)", "identity")
        self._detail_kv_row("Object Type", obj_type, "identity")
        self._detail_kv_row("Semantic Label", sem_label or "(none)", "identity")

        ui.Spacer(height=6)

        # ── Transform Section ──
        self._detail_section_header("Transform", "transform")
        if pos:
            self._detail_kv_row(
                "Position",
                f"X={pos.get('x', 0):.3f}  Y={pos.get('y', 0):.3f}  Z={pos.get('z', 0):.3f}",
                "transform",
            )
        else:
            self._detail_kv_row("Position", "(N/A)", "transform")
        if rot:
            self._detail_kv_row(
                "Rotation",
                f"X={rot.get('x', 0):.1f}°  Y={rot.get('y', 0):.1f}°  Z={rot.get('z', 0):.1f}°",
                "transform",
            )
        else:
            self._detail_kv_row("Rotation", "(N/A)", "transform")
        if scale:
            self._detail_kv_row(
                "Scale",
                f"X={scale.get('x', 1):.3f}  Y={scale.get('y', 1):.3f}  Z={scale.get('z', 1):.3f}",
                "transform",
            )
        else:
            self._detail_kv_row("Scale", "(default 1,1,1)", "transform")

        ui.Spacer(height=6)

        # ── Visual / Material Section ──
        self._detail_section_header("Visual", "visual")
        self._detail_kv_row("Visibility", visibility, "visual")
        self._detail_kv_row("Material Path", material or "(none)", "visual")

        ui.Spacer(height=6)

        # ── Hierarchy Section ──
        self._detail_section_header("Hierarchy", "hierarchy")
        self._detail_kv_row("Depth", str(depth), "hierarchy")
        self._detail_kv_row("Child Count", str(child_count), "hierarchy")

        ui.Spacer(height=6)

        # ── Raw Properties Section (collapsible) ──
        self._detail_section_header("Raw Properties (JSON)", "meta")
        self._render_properties_json(props_raw)

        self._set_status(
            f"[OK] Detail: {prim_path} (Static {obj_type})"
        )

    def _render_dynamic_object_detail(self, data: dict):
        """Render detail panel for a dynamic IoT object."""
        obj_id = data.get("object_id", "?")
        pos = data.get("position", {})
        rot = data.get("rotation", {})
        speed = data.get("speed", 0.0)
        space_id = data.get("space_id", self._current_space_id or "?")
        last_seen = data.get("last_seen", "N/A")
        status = data.get("status", "unknown")
        props_raw = data.get("properties", "{}")

        status_icon = self._STATUS_ICONS.get(status, "[?]")
        status_color = self._STATUS_COLORS.get(status, self._COLOR_GRAY)

        # ── Header ──
        with ui.VStack(spacing=2, height=0):
            with ui.HStack(height=28, spacing=8):
                ui.Label(
                    f"Dynamic Object: {obj_id}",
                    style={"color": self._COLOR_CYAN, "font_size": 16},
                    width=ui.Fraction(4),
                )
                ui.Label(
                    f"{status_icon} {status.upper()}",
                    style={"color": status_color, "font_size": 14},
                    alignment=ui.Alignment.RIGHT,
                    width=ui.Fraction(1),
                )
            ui.Spacer(height=4)

        # ── Status indicator bar ──
        with ui.ZStack(height=6):
            ui.Rectangle(style={"background_color": 0xFF333333, "border_radius": 3})
            ui.Rectangle(style={"background_color": status_color, "border_radius": 3})
        ui.Spacer(height=8)

        # ── Identity Section ──
        self._detail_section_header("Identity", "identity")
        self._detail_kv_row("Object ID", obj_id, "identity")
        self._detail_kv_row("Space ID", space_id, "identity")
        self._detail_kv_row("Status", f"{status_icon} {status}", "identity")

        ui.Spacer(height=6)

        # ── IoT / Sensor Data Section ──
        self._detail_section_header("IoT / Tracking Data", "iot")
        if pos:
            self._detail_kv_row(
                "Position",
                f"X={pos.get('x', 0):.3f}  Y={pos.get('y', 0):.3f}  Z={pos.get('z', 0):.3f}",
                "iot",
            )
        else:
            self._detail_kv_row("Position", "(N/A)", "iot")
        if rot:
            self._detail_kv_row(
                "Rotation",
                f"X={rot.get('x', 0):.1f}°  Y={rot.get('y', 0):.1f}°  Z={rot.get('z', 0):.1f}°",
                "iot",
            )
        else:
            self._detail_kv_row("Rotation", "(N/A)", "iot")
        self._detail_kv_row("Speed", f"{speed:.2f} m/s", "iot")
        self._detail_kv_row("Last Seen", str(last_seen)[:19] if last_seen else "N/A", "iot")

        ui.Spacer(height=6)

        # ── Raw Properties ──
        self._detail_section_header("Properties (JSON)", "meta")
        self._render_properties_json(props_raw)

        self._set_status(
            f"[OK] Detail: {obj_id} (Dynamic, status={status})"
        )

    # ── Detail Panel Helper Widgets ──────────────────────────────────

    def _detail_section_header(self, title: str, category: str):
        """Render a colored section header in the detail panel."""
        color = self._DETAIL_SECTION_COLORS.get(category, self._COLOR_WHITE)
        ui.Spacer(height=2)
        with ui.ZStack(height=22):
            ui.Rectangle(
                style={
                    "background_color": 0xFF1A1A2A,
                    "border_radius": 3,
                    "border_color": color,
                    "border_width": 1,
                },
            )
            ui.Label(
                f"  {title}",
                style={"color": color, "font_size": 13},
            )
        ui.Spacer(height=2)

    def _detail_kv_row(self, key: str, value: str, category: str = "meta"):
        """Render a key-value row in the detail panel."""
        key_color = self._DETAIL_SECTION_COLORS.get(category, self._COLOR_DIM)
        with ui.HStack(height=20, spacing=4):
            ui.Label(
                f"  {key}:",
                width=ui.Fraction(2),
                style={"color": key_color, "font_size": 12},
            )
            ui.Label(
                str(value),
                width=ui.Fraction(5),
                style={"color": self._COLOR_WHITE, "font_size": 12},
                word_wrap=True,
                tooltip=str(value),  # Full value on hover for long strings
            )

    def _render_properties_json(self, raw_json: str):
        """Parse and render a JSON properties string as indented key-value pairs.

        Falls back to displaying raw text if parsing fails.
        """
        if not raw_json or raw_json in ("{}", "null", "None"):
            ui.Label(
                "  (empty)",
                style={"color": self._COLOR_DIM, "font_size": 11},
            )
            return

        try:
            props = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except (json.JSONDecodeError, TypeError):
            # Show raw text if not valid JSON
            ui.Label(
                f"  {raw_json[:500]}",
                style={"color": self._COLOR_DIM, "font_size": 11},
                word_wrap=True,
            )
            return

        if not isinstance(props, dict):
            ui.Label(
                f"  {str(props)[:500]}",
                style={"color": self._COLOR_DIM, "font_size": 11},
                word_wrap=True,
            )
            return

        # Render up to 50 top-level keys to avoid UI slowdown
        max_keys = 50
        displayed = 0
        for key, value in props.items():
            if displayed >= max_keys:
                ui.Label(
                    f"  ... and {len(props) - max_keys} more properties",
                    style={"color": self._COLOR_DIM, "font_size": 11},
                )
                break

            # Format value: truncate long strings, pretty-print dicts/lists
            if isinstance(value, dict):
                val_str = json.dumps(value, ensure_ascii=False)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."
            elif isinstance(value, list):
                val_str = json.dumps(value, ensure_ascii=False)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."
            else:
                val_str = str(value)
                if len(val_str) > 120:
                    val_str = val_str[:117] + "..."

            with ui.HStack(height=18, spacing=4):
                ui.Label(
                    f"    {key}:",
                    width=ui.Fraction(2),
                    style={"color": 0xFFAAAACC, "font_size": 11},
                    tooltip=key,
                )
                ui.Label(
                    val_str,
                    width=ui.Fraction(5),
                    style={"color": self._COLOR_DIM, "font_size": 11},
                    word_wrap=True,
                    tooltip=str(value),  # Full value on hover
                )
            displayed += 1

    # =========================================================================
    #  HTTP Utilities (urllib — no extra packages required)
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

    # =========================================================================
    #  USD Value -> JSON Serialization
    # =========================================================================

    def _serialize_value(self, value):
        """Convert any USD value (Gf.Vec*, Gf.Matrix*, Vt.*Array, Sdf.AssetPath, etc.)
        into a JSON-serializable Python object."""
        if value is None:
            return None
        if isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, dict):
            return {str(k): self._serialize_value(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]

        # Sdf.AssetPath -> path string
        if hasattr(value, "resolvedPath") and hasattr(value, "path"):
            return value.path or value.resolvedPath or ""

        # Sdf.ListOp types (apiSchemas, etc.) -> item list
        if hasattr(value, "GetExplicitItems"):
            try:
                items = (
                    list(value.GetExplicitItems() or [])
                    + list(value.GetPrependedItems() or [])
                    + list(value.GetAppendedItems() or [])
                )
                return [self._serialize_value(v) for v in items] if items else []
            except Exception:
                return str(value)

        # Iterable USD types (Gf.Vec*, Gf.Matrix*, Gf.Quat*, Vt.*Array)
        try:
            return [self._serialize_value(v) for v in value]
        except (TypeError, ValueError):
            pass

        return str(value)

    # =========================================================================
    #  [Task 1] All Stage Prims -> Iceberg Table A
    # =========================================================================

    def _create_iceberg_export_frame(self):
        frame = CollapsableFrame("Task 1: Stage Prims -> Iceberg Table A", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Insert all Prim paths, types, and properties from the current\n"
                    "Stage into Iceberg static_db.table_a via the API middleware.\n"
                    "Properties include Attributes, Relationships, and Metadata\n"
                    "(Kind, CustomData, AssetInfo, apiSchemas, etc.).",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )
                btn = Button(
                    "Scan & Insert to Iceberg",
                    "SCAN & INSERT",
                    tooltip="All Stage Prims -> API -> Iceberg Table A",
                    on_click_fn=self._on_export_prims_to_iceberg,
                )
                self.wrapped_ui_elements.append(btn)

    def _collect_prim_records(self):
        """
        Traverse all Prims in the Stage and collect prim_path / type / properties (JSON).

        properties JSON structure:
        {
            "attributes": {
                "<attr_name>": {"value": ..., "typeName": "<SdfValueTypeName>"},
                ...
            },
            "relationships": {
                "<rel_name>": ["/target/path", ...],
                ...
            },
            "metadata": {
                "kind": "component",
                "active": true,
                "customData": {...},
                "assetInfo": {...},
                "apiSchemas": [...],
                ...
            }
        }
        """
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            return None, "No Stage is currently open."

        records = []
        for prim in stage.Traverse():
            prim_path = str(prim.GetPath())
            prim_type = prim.GetTypeName() or "Unknown"
            properties = {}

            # ----- 1. Attributes (Transform, Visual, Geometry, Semantics, etc.) -----
            attributes = {}
            for attr in prim.GetAttributes():
                attr_name = attr.GetName()
                try:
                    value = attr.Get()
                    if value is None:
                        continue
                    attributes[attr_name] = {
                        "value": self._serialize_value(value),
                        "typeName": str(attr.GetTypeName()),
                    }
                except Exception:
                    attributes[attr_name] = {"value": "<unreadable>", "typeName": "unknown"}
            if attributes:
                properties["attributes"] = attributes

            # ----- 2. Relationships (material binding, proxyPrim, etc.) -----
            relationships = {}
            for rel in prim.GetRelationships():
                rel_name = rel.GetName()
                targets = rel.GetTargets()
                relationships[rel_name] = [str(t) for t in targets]
            if relationships:
                properties["relationships"] = relationships

            # ----- 3. Metadata (Kind, CustomData, AssetInfo, apiSchemas, etc.) -----
            try:
                raw_metadata = prim.GetAllMetadata()
                metadata = {}
                for key, val in raw_metadata.items():
                    metadata[key] = self._serialize_value(val)

                # Also add appliedSchemas as a human-readable list
                applied = prim.GetAppliedSchemas()
                if applied:
                    metadata["_appliedSchemas"] = [str(s) for s in applied]

                if metadata:
                    properties["metadata"] = metadata
            except Exception:
                pass

            records.append(
                {
                    "prim_path": prim_path,
                    "type": prim_type,
                    "properties": json.dumps(properties, ensure_ascii=False),
                }
            )

        return records, None

    def _on_export_prims_to_iceberg(self):
        self._set_status("Scanning Stage Prims...")

        records, error = self._collect_prim_records()
        if error:
            self._set_status(f"[ERROR] {error}")
            return

        self._set_status(f"Collected {len(records)} Prims. Sending to API...")

        try:
            result = self._api_post_json(
                "api/v1/prims",
                {"records": records},
            )
            self._set_status(
                f"[DONE] {len(records)} records sent successfully.\n"
                f"API response: {json.dumps(result, ensure_ascii=False)}"
            )
        except urllib.error.URLError as e:
            # Local preview when API is not connected
            preview_lines = []
            for r in records[:3]:
                props = json.loads(r["properties"])
                attr_count = len(props.get("attributes", {}))
                rel_count = len(props.get("relationships", {}))
                meta_keys = list(props.get("metadata", {}).keys())
                preview_lines.append(
                    f"  {r['prim_path']} | {r['type']}\n"
                    f"    attrs={attr_count}, rels={rel_count}, metadata={meta_keys}"
                )
            self._set_status(
                f"[API NOT CONNECTED] {e}\n"
                f"Collected records: {len(records)} (format: prim_path | type | properties JSON)\n"
                f"-- First 3 preview --\n" + "\n".join(preview_lines)
            )
        except Exception as e:
            self._set_status(f"[ERROR] {e}\n{traceback.format_exc()}")

    # =========================================================================
    #  [Task 2] /World Direct Children -> USD -> S3
    # =========================================================================

    def _create_s3_export_frame(self):
        frame = CollapsableFrame("Task 2: /World Children -> USD -> S3", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Convert each direct child Prim under /World to a USD file\n"
                    "and upload to S3 storage via the API middleware.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._local_export_dir_field = StringField(
                    "Local Temp Path",
                    default_value="/tmp/isaac_usd_export",
                    tooltip="Temporary directory for exported USD files",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                    use_folder_picker=True,
                )
                self.wrapped_ui_elements.append(self._local_export_dir_field)

                btn = Button(
                    "Export /World Children -> USD -> S3",
                    "EXPORT USD -> S3",
                    tooltip="/World direct children -> USD conversion -> API -> S3 upload",
                    on_click_fn=self._on_export_world_children_to_s3,
                )
                self.wrapped_ui_elements.append(btn)

    def _export_prim_to_usd(self, prim, export_dir: str, flat_layer) -> str:
        """Export a Prim subtree to a single USD file."""
        from pxr import Sdf, Usd, UsdGeom

        prim_name = prim.GetName()
        export_path = os.path.join(export_dir, f"{prim_name}.usd")

        # Remove existing file first (Usd.Stage.CreateNew fails if file already exists)
        if os.path.exists(export_path):
            os.remove(export_path)

        export_stage = Usd.Stage.CreateNew(export_path)
        UsdGeom.SetStageUpAxis(export_stage, UsdGeom.Tokens.y)

        root_layer = export_stage.GetRootLayer()
        prim_path = prim.GetPath()

        # Create parent Prim hierarchy (e.g. /World)
        parent_path = prim_path.GetParentPath()
        if str(parent_path) not in ("/", ""):
            export_stage.DefinePrim(parent_path, "Xform")

        # Copy the full Prim spec (including children) from the flattened source
        Sdf.CopySpec(flat_layer, prim_path, root_layer, prim_path)

        export_stage.GetRootLayer().Save()
        return export_path

    def _on_export_world_children_to_s3(self):
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            self._set_status("[ERROR] No Stage is currently open.")
            return

        world_prim = stage.GetPrimAtPath("/World")
        if not world_prim.IsValid():
            self._set_status("[ERROR] /World Prim not found.")
            return

        children = list(world_prim.GetChildren())
        if not children:
            self._set_status("[WARN] No child Prims under /World.")
            return

        export_dir = self._local_export_dir_field.get_value()
        os.makedirs(export_dir, exist_ok=True)

        self._set_status(f"Converting {len(children)} /World children to USD...")

        # Flatten once for performance
        flat_layer = stage.Flatten()

        exported_files = []
        errors = []
        for child in children:
            try:
                usd_path = self._export_prim_to_usd(child, export_dir, flat_layer)
                exported_files.append(usd_path)
            except Exception as e:
                errors.append(f"  {child.GetPath()}: {e}")

        if errors:
            self._set_status("[CONVERSION ERROR]\n" + "\n".join(errors))
            return

        # Upload to S3 via API
        self._set_status(
            f"USD conversion done ({len(exported_files)} files). Uploading to S3 via API..."
        )

        uploaded = []
        upload_errors = []
        for local_path in exported_files:
            try:
                result = self._api_post_file(
                    "api/v1/upload-usd",
                    local_path,
                    fields={"prim_path": os.path.splitext(os.path.basename(local_path))[0]},
                )
                uploaded.append(result)
            except urllib.error.URLError:
                upload_errors.append(f"  {os.path.basename(local_path)}: API not connected")
            except Exception as e:
                upload_errors.append(f"  {os.path.basename(local_path)}: {e}")

        file_names = [os.path.basename(f) for f in exported_files]

        if upload_errors:
            self._set_status(
                f"[API NOT CONNECTED / ERROR] USD files saved locally.\n"
                f"Path: {export_dir}\n"
                f"Files: {file_names}\n"
                f"Upload errors:\n" + "\n".join(upload_errors)
            )
        else:
            self._set_status(
                f"[DONE] {len(uploaded)} USD files uploaded to S3.\n"
                f"Files: {file_names}\n"
                f"API response: {json.dumps(uploaded, ensure_ascii=False)}"
            )
