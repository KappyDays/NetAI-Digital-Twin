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

"""
UI Builder for the Space Heatmap extension.

Panel controls:
    1. Status/Log frame
    2. API Config frame (URL + health check)
    3. Heatmap Controls (auto-refresh, manual refresh, grid resolution, opacity)
    4. Legend (Green -> Yellow -> Red gradient)
    5. Space Summary (per-space congestion rows with drill-down)
"""

import asyncio
import os
import time

import omni.kit.app
import omni.ui as ui
from isaacsim.gui.components.element_wrappers import (
    Button,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .data_fetcher import HeatmapFetcher

# Default API URL
DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")

# Grid resolution options
GRID_RESOLUTION_OPTIONS = {"10x10": 10, "20x20": 20, "50x50": 50}


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        self._fetcher = HeatmapFetcher(on_status=self._safe_set_status)
        self._overlay_model = None
        self._auto_refresh_task = None
        self._auto_refresh_enabled = False
        self._refresh_interval = 10  # seconds
        self._grid_resolution = 20
        self._space_detail_frame = None
        self._space_rows_container = None
        self._pending_status = None  # status message from background thread

    def set_overlay_model(self, model):
        """Link the viewport overlay model so UI controls can update it."""
        self._overlay_model = model

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
        self._auto_refresh_enabled = False
        if self._auto_refresh_task:
            self._auto_refresh_task.cancel()
            self._auto_refresh_task = None
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()

    def build_ui(self):
        self._create_status_frame()
        self._create_api_config_frame()
        self._create_heatmap_controls_frame()
        self._create_legend_frame()
        self._create_space_summary_frame()

    # =========================================================================
    #  Status Log
    # =========================================================================

    def _create_status_frame(self):
        self._status_frame = CollapsableFrame("Status / Log", collapsed=False)
        with self._status_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._status_field = TextBlock(
                    "Last Operation",
                    num_lines=6,
                    tooltip="Operation results and logs",
                    include_copy_button=True,
                )

    def _set_status(self, message: str):
        self._status_field.set_text(message)

    def _safe_set_status(self, message: str):
        """Queue status message for main-thread update (called from background threads)."""
        self._pending_status = message

    def _flush_status(self):
        """Apply pending status message. Must be called from the main thread."""
        if self._pending_status is not None:
            self._set_status(self._pending_status)
            self._pending_status = None

    # =========================================================================
    #  API Middleware Configuration
    # =========================================================================

    def _create_api_config_frame(self):
        frame = CollapsableFrame("API Configuration", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._api_url_field = StringField(
                    "API Base URL",
                    default_value=DEFAULT_API_BASE_URL,
                    tooltip="Lakehouse API endpoint (e.g., http://lakehouse-api:8000)",
                    read_only=False,
                    on_value_changed_fn=self._on_api_url_changed,
                )
                self.wrapped_ui_elements.append(self._api_url_field)

                btn = Button(
                    "Health Check",
                    "CHECK",
                    tooltip="Test API connectivity",
                    on_click_fn=self._on_health_check,
                )
                self.wrapped_ui_elements.append(btn)

    def _on_api_url_changed(self, new_url):
        url = new_url.get_value_as_string() if hasattr(new_url, "get_value_as_string") else str(new_url)
        url = url.strip()
        if url:
            self._fetcher.api_base = url

    def _on_health_check(self):
        self._set_status("Checking API health...")

        def _check():
            return self._fetcher.check_health()

        async def _run():
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _check)
                self._flush_status()
                if result.success:
                    self._set_status(f"[OK] API healthy ({result.elapsed_ms:.0f}ms)")
                else:
                    self._set_status(f"[FAIL] API unreachable: {result.error}")
            except Exception as e:
                self._set_status(f"[ERROR] Health check failed: {e}")

        asyncio.ensure_future(_run())

    # =========================================================================
    #  Heatmap Controls
    # =========================================================================

    def _create_heatmap_controls_frame(self):
        frame = CollapsableFrame("Heatmap Controls", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                # Auto-refresh toggle
                with ui.HStack(spacing=10, height=0):
                    ui.Label("Auto-Refresh", width=100)
                    self._auto_refresh_checkbox = ui.CheckBox(width=24, height=24)
                    self._auto_refresh_checkbox.model.set_value(False)
                    self._auto_refresh_checkbox.model.add_value_changed_fn(self._on_auto_refresh_toggled)

                # Refresh interval slider (5-60 seconds)
                with ui.HStack(spacing=10, height=0):
                    ui.Label("Interval (s)", width=100)
                    self._interval_slider = ui.IntSlider(min=5, max=60, height=24)
                    self._interval_slider.model.set_value(10)
                    self._interval_slider.model.add_value_changed_fn(self._on_interval_changed)

                # Manual refresh button
                btn = Button(
                    "Refresh Now",
                    "REFRESH",
                    tooltip="Manually fetch latest congestion data",
                    on_click_fn=self._on_manual_refresh,
                )
                self.wrapped_ui_elements.append(btn)

                # Grid resolution dropdown
                with ui.HStack(spacing=10, height=0):
                    ui.Label("Grid Resolution", width=100)
                    self._resolution_combo = ui.ComboBox(1)  # default index 1 = 20x20
                    for label in GRID_RESOLUTION_OPTIONS:
                        self._resolution_combo.model.append_child_item(
                            None, ui.SimpleStringModel(label)
                        )
                    self._resolution_combo.model.add_item_changed_fn(self._on_resolution_changed)

                # Opacity slider
                with ui.HStack(spacing=10, height=0):
                    ui.Label("Opacity", width=100)
                    self._opacity_slider = ui.FloatSlider(min=0.1, max=1.0, height=24)
                    self._opacity_slider.model.set_value(0.4)
                    self._opacity_slider.model.add_value_changed_fn(self._on_opacity_changed)

                # Show/hide grid toggle
                with ui.HStack(spacing=10, height=0):
                    ui.Label("Show Overlay", width=100)
                    self._show_grid_checkbox = ui.CheckBox(width=24, height=24)
                    self._show_grid_checkbox.model.set_value(True)
                    self._show_grid_checkbox.model.add_value_changed_fn(self._on_show_grid_toggled)

    def _on_auto_refresh_toggled(self, model):
        self._auto_refresh_enabled = model.get_value_as_bool()
        if self._auto_refresh_enabled:
            self._set_status("[INFO] Auto-refresh enabled")
            self._auto_refresh_task = asyncio.ensure_future(self._auto_refresh_loop())
        else:
            self._set_status("[INFO] Auto-refresh disabled")
            if self._auto_refresh_task:
                self._auto_refresh_task.cancel()
                self._auto_refresh_task = None

    def _on_interval_changed(self, model):
        self._refresh_interval = model.get_value_as_int()

    def _on_resolution_changed(self, model, item):
        try:
            idx = model.get_item_value_model().get_value_as_int()
            labels = list(GRID_RESOLUTION_OPTIONS.keys())
            if 0 <= idx < len(labels):
                self._grid_resolution = GRID_RESOLUTION_OPTIONS[labels[idx]]
        except Exception as e:
            import omni.kit.app
            omni.kit.app.get_app().print_and_log(f"[KKR.SpaceHeatmap] Resolution change error: {e}")

    def _on_opacity_changed(self, model):
        val = model.get_value_as_float()
        if self._overlay_model:
            self._overlay_model.set_opacity(val)

    def _on_show_grid_toggled(self, model):
        val = model.get_value_as_bool()
        if self._overlay_model:
            self._overlay_model.set_show_grid(val)

    def _on_manual_refresh(self):
        self._set_status("Refreshing congestion data...")
        asyncio.ensure_future(self._do_refresh())

    async def _do_refresh(self):
        """Fetch both summary and grid data, update overlay model."""
        loop = asyncio.get_running_loop()

        try:
            # Fetch summary
            result = await loop.run_in_executor(
                None, self._fetcher.fetch_congestion_summary
            )
            self._flush_status()
            if result.success and self._overlay_model:
                self._overlay_model.set_spaces(result.data.spaces)
                self._update_space_summary_ui(result.data)

            # Fetch grid
            res = self._grid_resolution

            def _fetch_grid():
                return self._fetcher.fetch_congestion_grid(rows=res, cols=res)

            grid_result = await loop.run_in_executor(None, _fetch_grid)
            self._flush_status()
            if grid_result.success and self._overlay_model:
                self._overlay_model.set_grid(grid_result.data)

            snapshot = result.data.snapshot_time if result.success else "N/A"
            source = result.source if result.success else "error"
            self._set_status(
                f"[OK] Refreshed at {snapshot} (source: {source})"
            )
        except Exception as e:
            self._set_status(f"[ERROR] Refresh failed: {e}")

    async def _auto_refresh_loop(self):
        """Periodically refresh congestion data."""
        while self._auto_refresh_enabled:
            try:
                await self._do_refresh()
            except Exception as e:
                self._set_status(f"[ERROR] Auto-refresh: {e}")

            # Wait for interval using wall-clock time
            start = time.monotonic()
            while time.monotonic() - start < self._refresh_interval:
                if not self._auto_refresh_enabled:
                    return
                await omni.kit.app.get_app().next_update_async()

    # =========================================================================
    #  Legend (Green -> Yellow -> Red gradient)
    # =========================================================================

    def _create_legend_frame(self):
        frame = CollapsableFrame("Legend", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                # Gradient bar using 5 colored rectangles
                with ui.HStack(spacing=0, height=20):
                    # Green
                    ui.Rectangle(
                        width=ui.Fraction(1),
                        style={"background_color": ui.color(0, 255, 0, 200)},
                    )
                    # Green-Yellow
                    ui.Rectangle(
                        width=ui.Fraction(1),
                        style={"background_color": ui.color(128, 255, 0, 200)},
                    )
                    # Yellow
                    ui.Rectangle(
                        width=ui.Fraction(1),
                        style={"background_color": ui.color(255, 255, 0, 200)},
                    )
                    # Yellow-Red
                    ui.Rectangle(
                        width=ui.Fraction(1),
                        style={"background_color": ui.color(255, 128, 0, 200)},
                    )
                    # Red
                    ui.Rectangle(
                        width=ui.Fraction(1),
                        style={"background_color": ui.color(255, 0, 0, 200)},
                    )

                # Labels
                with ui.HStack(spacing=0, height=0):
                    ui.Label("Low", alignment=ui.Alignment.LEFT, width=ui.Fraction(1))
                    ui.Label("Medium", alignment=ui.Alignment.CENTER, width=ui.Fraction(1))
                    ui.Label("High", alignment=ui.Alignment.RIGHT, width=ui.Fraction(1))

    # =========================================================================
    #  Space Summary (per-space congestion rows)
    # =========================================================================

    def _create_space_summary_frame(self):
        frame = CollapsableFrame("Space Summary", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                btn = Button(
                    "Load Summary",
                    "LOAD",
                    tooltip="Fetch space congestion summary",
                    on_click_fn=self._on_load_summary,
                )
                self.wrapped_ui_elements.append(btn)

                self._space_rows_container = ui.VStack(spacing=3, height=0)
                self._space_detail_frame = CollapsableFrame(
                    "Space Detail", collapsed=True
                )

    def _on_load_summary(self):
        self._set_status("Loading space summary...")
        asyncio.ensure_future(self._do_load_summary())

    async def _do_load_summary(self):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, self._fetcher.fetch_congestion_summary
        )
        self._flush_status()
        if result.success:
            self._update_space_summary_ui(result.data)
            self._set_status(
                f"[OK] Loaded {result.data.total_spaces} spaces "
                f"(source: {result.source})"
            )
        else:
            self._set_status(f"[FAIL] Load summary: {result.error}")

    def _update_space_summary_ui(self, summary):
        """Rebuild the space rows container with current data."""
        if not self._space_rows_container:
            return

        self._space_rows_container.clear()
        with self._space_rows_container:
            for space in summary.spaces:
                self._build_space_row(space)

    def _build_space_row(self, space):
        """Build a single space row with colored indicator + labels."""
        r, g, b = self._congestion_to_rgb(space.congestion_level)

        with ui.HStack(spacing=5, height=24):
            # Colored status indicator
            ui.Rectangle(
                width=16,
                height=16,
                style={"background_color": ui.color(r, g, b, 255)},
            )
            # Space ID
            ui.Label(
                space.display_name,
                width=120,
                tooltip=f"Space: {space.space_id}",
            )
            # Congestion level
            ui.Label(
                f"{space.congestion_level:.0%}",
                width=50,
            )
            # Counts
            ui.Label(
                f"S:{space.static_count} D:{space.dynamic_count} T:{space.total_count}",
                width=ui.Fraction(1),
            )
            # Detail button
            detail_btn = ui.Button(
                "Detail",
                width=50,
                height=20,
                clicked_fn=lambda s=space: self._show_space_detail(s),
            )

    def _show_space_detail(self, space):
        """Show detail panel for a specific space."""
        if not self._space_detail_frame:
            return

        self._space_detail_frame.collapsed = False
        self._space_detail_frame.clear()
        with self._space_detail_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    f"Space: {space.display_name}",
                    style={"font_size": 16},
                    height=24,
                )
                ui.Label(f"Congestion Level: {space.congestion_level:.1%} ({space.congestion_label})")
                ui.Label(f"Static Objects: {space.static_count}")
                ui.Label(f"Dynamic Objects: {space.dynamic_count}")
                ui.Label(f"Total Objects: {space.total_count}")

                if space.type_distribution:
                    ui.Label("Type Distribution:", height=20)
                    for type_name, count in space.type_distribution.items():
                        with ui.HStack(spacing=5, height=20):
                            ui.Spacer(width=20)
                            ui.Label(f"{type_name}: {count}")

    @staticmethod
    def _congestion_to_rgb(level):
        """Convert congestion level (0-1) to RGB tuple."""
        level = max(0.0, min(1.0, level))
        if level < 0.5:
            t = level / 0.5
            return int(255 * t), 255, 0
        else:
            t = (level - 0.5) / 0.5
            return 255, int(255 * (1.0 - t)), 0
