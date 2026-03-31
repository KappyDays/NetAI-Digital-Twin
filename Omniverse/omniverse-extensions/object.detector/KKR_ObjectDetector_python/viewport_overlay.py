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
Viewport Overlay -- renders bounding boxes and class labels in the 3D viewport.

Uses omni.ui.scene primitives (sc.Line, sc.Label, sc.Transform) to draw
detection results as colored rectangles with class labels in NDC coordinates.

Pixel to NDC conversion:
    ndc_x = (px / img_w) * 2 - 1
    ndc_y = 1 - (py / img_h) * 2

Color format: 0xAABBGGRR (omni.ui convention).
"""

from omni.ui import scene as sc
import omni.ui as ui


class BBoxManipulator(sc.Manipulator):
    """Renders detection bounding boxes and labels in the viewport using NDC coordinates."""

    # Color palette per class name (0xAABBGGRR format)
    CLASS_COLORS = {
        "person": 0xFF4444FF,       # Red
        "chair": 0xFF44FF44,        # Green
        "couch": 0xFFFF8844,        # Light blue
        "bed": 0xFF4488FF,          # Orange
        "dining table": 0xFF44FFFF, # Yellow
        "tv": 0xFFFF44FF,           # Magenta
        "laptop": 0xFFFFFF44,       # Cyan
        "car": 0xFF8844FF,          # Pink
        "truck": 0xFF44FFAA,        # Lime
        "dog": 0xFFFF4488,          # Purple
        "cat": 0xFF88FF44,          # Chartreuse
        "bottle": 0xFF4488AA,       # Brown-ish
        "cup": 0xFFAAAAFF,          # Light pink
        "book": 0xFFAAFFAA,         # Light green
        "cell phone": 0xFFFFAAAA,   # Light cyan
    }
    DEFAULT_COLOR = 0xFF00CCFF  # Amber

    # Line thickness for bbox
    _THICKNESS = 5

    def on_build(self):
        """Called by the scene framework to build/rebuild the visual elements."""
        model = self.model
        if not model or not model.detections:
            return

        img_w = model.image_width
        img_h = model.image_height

        for det in model.detections:
            # Pixel to NDC conversion: range [-1, 1]
            ndc_x1 = (det.x1 / img_w) * 2 - 1
            ndc_y1 = 1 - (det.y1 / img_h) * 2
            ndc_x2 = (det.x2 / img_w) * 2 - 1
            ndc_y2 = 1 - (det.y2 / img_h) * 2

            color = self.CLASS_COLORS.get(det.class_name, self.DEFAULT_COLOR)
            thickness = self._THICKNESS

            # Draw rectangle with 4 sc.Line segments (top, right, bottom, left)
            # Z=0 keeps lines on the near plane of the SceneView
            sc.Line([ndc_x1, ndc_y1, 0], [ndc_x2, ndc_y1, 0], color=color, thickness=thickness)
            sc.Line([ndc_x2, ndc_y1, 0], [ndc_x2, ndc_y2, 0], color=color, thickness=thickness)
            sc.Line([ndc_x2, ndc_y2, 0], [ndc_x1, ndc_y2, 0], color=color, thickness=thickness)
            sc.Line([ndc_x1, ndc_y2, 0], [ndc_x1, ndc_y1, 0], color=color, thickness=thickness)

            # Label at top-left corner of the bounding box
            with sc.Transform(
                transform=sc.Matrix44.get_translation_matrix(ndc_x1, ndc_y1, 0)
            ):
                sc.Label(
                    f"{det.class_name} {det.confidence:.0%}",
                    size=18,
                    color=color,
                    alignment=ui.Alignment.LEFT_BOTTOM,
                )

    def on_model_updated(self, item):
        """Called when the model signals a data change. Triggers a rebuild."""
        self.invalidate()
