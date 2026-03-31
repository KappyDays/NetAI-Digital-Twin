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
import os
import traceback

import omni.ui as ui
from isaacsim.gui.components.element_wrappers import (
    Button,
    CheckBox,
    CollapsableFrame,
    FloatField,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .data_fetcher import (
    TrajectoryFetcher,
    generate_demo_trajectories,
    generate_demo_latest,
)

# API middleware URL (env-var-driven for Docker/k8s portability).
DEFAULT_API_BASE_URL = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")


class UIBuilder:
    """Panel UI for the Dynamic Tracker extension.

    Provides controls for:
        - API configuration and health checking
        - Dynamic object discovery and selection
        - Time range specification and trajectory fetching
        - Display settings (line thickness, speed coloring, labels)
    """

    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        self._fetcher = TrajectoryFetcher()
        self._overlay_model = None  # Set by extension.py via set_overlay_model()
        self._selected_objects = {}  # {object_id: bool}
        self._object_checkboxes = {}  # {object_id: ui.CheckBox}

    def set_overlay_model(self, model):
        """Called by extension.py to share the viewport overlay model."""
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
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()
        self._object_checkboxes = {}

    def build_ui(self):
        self._create_status_frame()
        self._create_api_config_frame()
        self._create_object_selector_frame()
        self._create_time_range_frame()
        self._create_display_settings_frame()

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
                    on_value_changed_fn=self._on_api_url_changed,
                )
                self.wrapped_ui_elements.append(self._api_url_field)

                self._health_btn = Button(
                    "Health Check",
                    "Check API Health",
                    tooltip="Test connection to the Lakehouse API",
                    on_click_fn=self._on_health_check,
                )
                self.wrapped_ui_elements.append(self._health_btn)

    def _on_api_url_changed(self, value):
        url = value.get_value_as_string() if hasattr(value, "get_value_as_string") else str(value)
        self._fetcher.api_base = url.strip()
        self._set_status(f"API URL updated: {self._fetcher.api_base}")

    def _on_health_check(self):
        self._set_status("Checking API health...")

        def _do_check():
            return self._fetcher.check_health()

        async def _async_check():
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _do_check)
                if result.success:
                    self._set_status(
                        f"[OK] API healthy ({result.elapsed_ms:.0f}ms)\n"
                        f"Response: {result.data}"
                    )
                else:
                    self._set_status(f"[FAIL] API unreachable: {result.error}")
            except Exception as e:
                self._set_status(f"[ERROR] Health check failed: {e}")

        asyncio.ensure_future(_async_check())

    # =========================================================================
    #  Object Selector
    # =========================================================================

    def _create_object_selector_frame(self):
        self._obj_selector_frame = CollapsableFrame("Object Selector", collapsed=False)
        with self._obj_selector_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Select dynamic objects to visualize trajectories.\n"
                    "Click 'Refresh Objects' to discover available objects from the API.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._refresh_objects_btn = Button(
                    "Refresh Objects",
                    "Refresh Objects",
                    tooltip="Fetch available dynamic object tables from the API",
                    on_click_fn=self._on_refresh_objects,
                )
                self.wrapped_ui_elements.append(self._refresh_objects_btn)

                # Container for dynamic checkboxes
                self._objects_container = ui.VStack(spacing=3, height=0)

                self._demo_btn = Button(
                    "Load Demo Data",
                    "Load Demo Data",
                    tooltip="Load demo trajectories without API connection",
                    on_click_fn=self._on_load_demo,
                )
                self.wrapped_ui_elements.append(self._demo_btn)

    def _on_refresh_objects(self):
        self._set_status("Refreshing dynamic objects list...")

        def _do_fetch():
            return self._fetcher.fetch_dynamic_tables()

        async def _async_fetch():
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _do_fetch)
                if result.success:
                    table_names = result.data  # list[str]
                    self._populate_object_checkboxes(table_names)
                    self._set_status(
                        f"[OK] Found {len(table_names)} dynamic objects "
                        f"(source: {result.source}, {result.elapsed_ms:.0f}ms)"
                    )
                else:
                    self._set_status(f"[FAIL] Could not fetch objects: {result.error}")
            except Exception as e:
                self._set_status(f"[ERROR] Refresh failed: {e}\n{traceback.format_exc()}")

        asyncio.ensure_future(_async_fetch())

    def _populate_object_checkboxes(self, object_ids):
        """Rebuild the checkboxes for discovered object IDs."""
        self._object_checkboxes = {}
        self._selected_objects = {oid: True for oid in object_ids}

        # Rebuild container
        self._objects_container.clear()
        with self._objects_container:
            for oid in object_ids:
                with ui.HStack(spacing=5, height=0):
                    cb = ui.CheckBox(width=20)
                    cb.model.set_value(True)
                    cb.model.add_value_changed_fn(
                        lambda m, obj_id=oid: self._on_object_toggled(obj_id, m.get_value_as_bool())
                    )
                    self._object_checkboxes[oid] = cb
                    ui.Label(oid, word_wrap=False)

    def _on_object_toggled(self, object_id, checked):
        self._selected_objects[object_id] = checked

    def _on_load_demo(self):
        """Load demo trajectories directly into the viewport overlay."""
        try:
            trajectories = generate_demo_trajectories()
            demo_ids = [t.object_id for t in trajectories]
            self._populate_object_checkboxes(demo_ids)

            if self._overlay_model:
                self._overlay_model.set_trajectories(trajectories)
                self._set_status(
                    f"[DEMO] Loaded {len(trajectories)} demo trajectories "
                    f"({sum(len(t.points) for t in trajectories)} total points)"
                )
            else:
                self._set_status("[WARN] Viewport overlay not available. Demo data loaded but not visualized.")
        except Exception as e:
            self._set_status(f"[ERROR] Failed to load demo data: {e}")

    # =========================================================================
    #  Time Range & Trajectory Fetch
    # =========================================================================

    def _create_time_range_frame(self):
        frame = CollapsableFrame("Time Range & Fetch", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Specify the time range for trajectory queries (ISO 8601).\n"
                    "Use the slider to scrub through time after fetching.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._start_time_field = StringField(
                    "Start Time (ISO 8601)",
                    default_value="2026-03-24T00:00:00Z",
                    tooltip="Trajectory query start time",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._start_time_field)

                self._end_time_field = StringField(
                    "End Time (ISO 8601)",
                    default_value="2026-03-24T01:00:00Z",
                    tooltip="Trajectory query end time",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._end_time_field)

                # Sample interval
                self._sample_interval_field = StringField(
                    "Sample Interval (seconds)",
                    default_value="5",
                    tooltip="Time interval between trajectory samples",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._sample_interval_field)

                # Time scrub slider
                ui.Label("Time Scrub", style={"color": 0xFFCCCCCC})
                self._time_slider = ui.FloatSlider(min=0.0, max=1.0, step=0.01)
                self._time_slider.model.set_value(1.0)
                self._time_slider.model.add_value_changed_fn(self._on_time_slider_changed)

                self._fetch_btn = Button(
                    "Fetch Trajectories",
                    "Fetch Trajectories",
                    tooltip="Fetch trajectory data for selected objects from the API",
                    on_click_fn=self._on_fetch_trajectories,
                )
                self.wrapped_ui_elements.append(self._fetch_btn)

    def _on_time_slider_changed(self, model):
        frac = model.get_value_as_float()
        if self._overlay_model:
            self._overlay_model.set_time_fraction(frac)

    def _on_fetch_trajectories(self):
        selected = [oid for oid, checked in self._selected_objects.items() if checked]
        if not selected:
            self._set_status("[WARN] No objects selected. Select objects first.")
            return

        start_time = self._start_time_field.get_value()
        end_time = self._end_time_field.get_value()

        try:
            sample_interval = int(self._sample_interval_field.get_value())
        except (ValueError, TypeError):
            sample_interval = 5

        self._set_status(f"Fetching trajectories for {len(selected)} objects...")

        def _do_fetch():
            trajectories = []
            errors = []
            for oid in selected:
                result = self._fetcher.fetch_trajectory(
                    object_id=oid,
                    start_time=start_time,
                    end_time=end_time,
                    sample_interval=sample_interval,
                )
                if result.success and result.data:
                    trajectories.append(result.data)
                else:
                    errors.append(f"{oid}: {result.error}")
            return trajectories, errors

        async def _async_fetch():
            try:
                loop = asyncio.get_running_loop()
                trajectories, errors = await loop.run_in_executor(None, _do_fetch)

                if trajectories and self._overlay_model:
                    self._overlay_model.set_trajectories(trajectories)

                total_pts = sum(len(t.points) for t in trajectories)
                status_lines = [
                    f"[OK] Fetched {len(trajectories)} trajectories ({total_pts} total points)"
                ]
                if errors:
                    status_lines.append(f"[WARN] {len(errors)} errors:")
                    for err in errors:
                        status_lines.append(f"  - {err}")
                self._set_status("\n".join(status_lines))

            except Exception as e:
                self._set_status(f"[ERROR] Fetch failed: {e}\n{traceback.format_exc()}")

        asyncio.ensure_future(_async_fetch())

    # =========================================================================
    #  Display Settings
    # =========================================================================

    def _create_display_settings_frame(self):
        frame = CollapsableFrame("Display Settings", collapsed=True)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                # Line thickness
                ui.Label("Line Thickness", style={"color": 0xFFCCCCCC})
                self._thickness_slider = ui.FloatSlider(min=0.5, max=10.0, step=0.5)
                self._thickness_slider.model.set_value(2.0)
                self._thickness_slider.model.add_value_changed_fn(self._on_thickness_changed)

                # Speed coloring
                with ui.HStack(spacing=5, height=0):
                    self._speed_color_cb = ui.CheckBox(width=20)
                    self._speed_color_cb.model.set_value(False)
                    self._speed_color_cb.model.add_value_changed_fn(self._on_speed_color_toggled)
                    ui.Label("Speed-Based Coloring", word_wrap=False)
                    ui.Label(
                        "(blue=slow, red=fast)",
                        style={"color": 0xFF888888},
                        word_wrap=False,
                    )

                # Labels
                with ui.HStack(spacing=5, height=0):
                    self._labels_cb = ui.CheckBox(width=20)
                    self._labels_cb.model.set_value(True)
                    self._labels_cb.model.add_value_changed_fn(self._on_labels_toggled)
                    ui.Label("Show Object Labels", word_wrap=False)

    def _on_thickness_changed(self, model):
        thickness = model.get_value_as_float()
        if self._overlay_model:
            self._overlay_model.set_line_thickness(thickness)

    def _on_speed_color_toggled(self, model):
        enabled = model.get_value_as_bool()
        if self._overlay_model:
            self._overlay_model.set_show_speed_colors(enabled)

    def _on_labels_toggled(self, model):
        enabled = model.get_value_as_bool()
        if self._overlay_model:
            self._overlay_model.set_show_labels(enabled)
