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
Viewport Overlay — renders trajectory polylines and position markers in the 3D viewport.

Uses omni.ui.scene primitives (sc.Line, sc.Label, sc.Transform) to draw
dynamic object trajectories as colored polylines with optional speed-based
coloring and object ID labels.

Color format: 0xAABBGGRR (omni.ui convention).
"""

from omni.ui import scene as sc
import omni.ui as ui


class TrajectoryManipulator(sc.Manipulator):
    """Renders trajectory polylines and position markers in the viewport."""

    # Object color palette (0xAABBGGRR format)
    PALETTE = [
        0xFFFF4444,  # Blue (BGR)
        0xFF44FF44,  # Green
        0xFF4488FF,  # Orange
        0xFFFF44FF,  # Magenta
        0xFF44FFFF,  # Yellow
        0xFFFFFF44,  # Cyan
    ]

    def on_build(self):
        """Called by the scene framework to build/rebuild the visual elements."""
        model = self.model
        if not model or not model.trajectories:
            return

        time_frac = model.time_fraction
        thickness = model.line_thickness

        for idx, traj in enumerate(model.trajectories):
            points = traj.points
            if not points:
                continue

            # Determine how many points to show based on time slider
            end_idx = max(1, int(len(points) * time_frac))
            visible_points = points[:end_idx]

            color_base = traj.color if traj.color else self.PALETTE[idx % len(self.PALETTE)]

            # Draw polyline segments
            for i in range(len(visible_points) - 1):
                p1 = visible_points[i]
                p2 = visible_points[i + 1]

                if model.show_speed_colors:
                    # Interpolate blue (slow) to red (fast) based on speed
                    speed = p2.speed if hasattr(p2, "speed") else 0.0
                    color = self._speed_to_color(speed)
                else:
                    color = color_base

                sc.Line(
                    [p1.pos_x, p1.pos_y, p1.pos_z],
                    [p2.pos_x, p2.pos_y, p2.pos_z],
                    color=ui.color(color),
                    thickness=thickness,
                )

            # Draw current position marker (last visible point) with label
            if visible_points and model.show_labels:
                last = visible_points[-1]
                with sc.Transform(
                    transform=sc.Matrix44.get_translation_matrix(
                        last.pos_x, last.pos_y, last.pos_z + 0.5
                    ),
                    look_at=sc.Transform.LookAt.CAMERA,
                ):
                    sc.Label(
                        traj.object_id,
                        size=14,
                        color=ui.color(color_base),
                        alignment=ui.Alignment.CENTER,
                    )

    def on_model_updated(self, item):
        """Called when the model signals a data change. Triggers a rebuild."""
        self.invalidate()

    @staticmethod
    def _speed_to_color(speed, max_speed=3.0):
        """Interpolate blue(slow) → green → yellow → red(fast). Returns 0xAABBGGRR."""
        ratio = min(speed / max(max_speed, 0.01), 1.0)
        if ratio < 0.5:
            # Blue to Green
            t = ratio / 0.5
            r = 0
            g = int(255 * t)
            b = int(255 * (1.0 - t))
        else:
            # Green to Red
            t = (ratio - 0.5) / 0.5
            r = int(255 * t)
            g = int(255 * (1.0 - t))
            b = 0
        return 0xFF000000 | r | (g << 8) | (b << 16)
