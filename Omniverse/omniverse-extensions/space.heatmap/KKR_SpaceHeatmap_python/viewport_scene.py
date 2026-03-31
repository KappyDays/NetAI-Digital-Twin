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
Viewport Scene -- manages sc.SceneView registration with the viewport API.

Canonical copy. Sibling: dynamic.tracker/KKR_DynamicTracker_python/viewport_scene.py
Based on: isaacsim.ros2.tf_viewer/impl/viewport_scene.py
"""

from omni.ui import scene as sc
import omni.kit.viewport.utility

from .overlay_model import HeatmapOverlayModel
from .viewport_overlay import HeatmapManipulator


class ViewportScene:
    def __init__(self, ext_id: str):
        self._ext_id = ext_id
        self._scene_view = None
        self._viewport_api = None
        self.model = HeatmapOverlayModel()

        vp_win = omni.kit.viewport.utility.get_active_viewport_window()
        if vp_win is None:
            raise RuntimeError("No active viewport window")

        self._viewport_api = vp_win.viewport_api

        with vp_win.get_frame(ext_id):
            self._scene_view = sc.SceneView(
                aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT
            )
            with self._scene_view.scene:
                self._manipulator = HeatmapManipulator(model=self.model)

        # CRITICAL: register with viewport API for camera tracking
        self._viewport_api.add_scene_view(self._scene_view)

    def destroy(self):
        HeatmapManipulator.cleanup_cache()
        if self._scene_view and self._viewport_api:
            self._viewport_api.remove_scene_view(self._scene_view)
            self._scene_view.scene.clear()
            self._scene_view = None
        self._manipulator = None
        self.model = None
