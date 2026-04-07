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
import gc

import omni
import omni.kit.commands
import omni.timeline
import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import ScrollingWindow
from isaacsim.gui.components.menu import MenuItemDescription
from omni.kit.menu.utils import add_menu_items, remove_menu_items
from omni.usd import StageEventType

from .global_variables import EXTENSION_TITLE
from .ui_builder import UIBuilder

"""
This file serves as a basic template for the standard boilerplate operations
that make a UI-based extension appear on the toolbar.

This implementation is meant to cover most use-cases without modification.
Various callbacks are hooked up to a seperate class UIBuilder in .ui_builder.py
Most users will be able to make their desired UI extension by interacting solely with
UIBuilder.

This class sets up standard useful callback functions in UIBuilder:
    on_menu_callback: Called when extension is opened
    on_timeline_event: Called when timeline is stopped, paused, or played
    on_stage_event: Called when stage is opened or closed
    cleanup: Called when resources should be cleaned up
    build_ui: User function that creates the UI they want.
"""


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        """Initialize extension and UI elements"""

        self.ext_id = ext_id
        self._usd_context = omni.usd.get_context()

        # Build Window
        self._window = ScrollingWindow(
            title=EXTENSION_TITLE, width=500, height=600, visible=False, dockPreference=ui.DockPreference.LEFT_BOTTOM
        )
        self._window.set_visibility_changed_fn(self._on_window)

        # Register menu under Tools > KKR-Tools with checkmark toggle
        self._ext_id = ext_id
        self._action_name = f"ToggleWindow:{EXTENSION_TITLE}"
        action_registry = omni.kit.actions.core.get_action_registry()
        action_registry.register_action(
            ext_id,
            self._action_name,
            self._menu_callback,
            description=f"Toggle {EXTENSION_TITLE} window",
        )
        self._menu_items = [
            MenuItemDescription(
                name=EXTENSION_TITLE,
                ticked=True,
                ticked_fn=lambda: self._window.visible if self._window else False,
                onclick_action=(ext_id, self._action_name),
            )
        ]
        self._menu_items = [MenuItemDescription(name="KKR-Tools", sub_menu=self._menu_items)]
        add_menu_items(self._menu_items, "Tools")

        # Filled in with User Functions
        self.ui_builder = UIBuilder()

        # Events
        self._usd_context = omni.usd.get_context()
        self._stage_event_sub = None
        self._timeline = omni.timeline.get_timeline_interface()

    def on_shutdown(self):
        remove_menu_items(self._menu_items, "Tools")

        action_registry = omni.kit.actions.core.get_action_registry()
        action_registry.deregister_action(self._ext_id, self._action_name)

        if self._window:
            self._window = None
        self.ui_builder.cleanup()
        gc.collect()

    def _on_window(self, visible):
        if self._window.visible:
            # Subscribe to Stage and Timeline Events
            self._usd_context = omni.usd.get_context()
            events = self._usd_context.get_stage_event_stream()
            self._stage_event_sub = events.create_subscription_to_pop(self._on_stage_event)
            stream = self._timeline.get_timeline_event_stream()
            self._timeline_event_sub = stream.create_subscription_to_pop(self._on_timeline_event)

            self._build_ui()
        else:
            self._usd_context = None
            self._stage_event_sub = None
            self._timeline_event_sub = None
            self.ui_builder.cleanup()

    def _build_ui(self):
        with self._window.frame:
            with ui.VStack(spacing=5, height=0):
                self._build_extension_ui()

        async def dock_window():
            await omni.kit.app.get_app().next_update_async()

            def dock(space, name, location, pos=0.5):
                window = omni.ui.Workspace.get_window(name)
                if window and space:
                    window.dock_in(space, location, pos)
                return window

            tgt = ui.Workspace.get_window("Viewport")
            dock(tgt, EXTENSION_TITLE, omni.ui.DockPosition.LEFT, 0.33)
            await omni.kit.app.get_app().next_update_async()

        self._task = asyncio.ensure_future(dock_window())

    #################################################################
    # Functions below this point call user functions
    #################################################################

    def _menu_callback(self):
        self._window.visible = not self._window.visible
        self.ui_builder.on_menu_callback()

    def _on_timeline_event(self, event):
        self.ui_builder.on_timeline_event(event)

    def _on_stage_event(self, event):
        if event.type == int(StageEventType.OPENED) or event.type == int(StageEventType.CLOSED):
            # stage was opened or closed, cleanup
            self.ui_builder.cleanup()

        self.ui_builder.on_stage_event(event)

    def _build_extension_ui(self):
        # Call user function for building UI
        self.ui_builder.build_ui()
