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

from omni.ui import scene as sc


class TrajectoryOverlayModel(sc.AbstractManipulatorModel):
    """Data model for trajectory overlay. Holds trajectory data and signals changes."""

    class PositionItem(sc.AbstractManipulatorItem):
        def __init__(self):
            super().__init__()
            self.value = [0, 0, 0]

    def __init__(self):
        super().__init__()
        self._trajectories = []  # list of ObjectTrajectory
        self._time_fraction = 1.0  # 0.0 to 1.0 slider position
        self._show_speed_colors = False
        self._show_labels = True
        self._line_thickness = 2.0

    @property
    def trajectories(self):
        return self._trajectories

    def set_trajectories(self, trajectories):
        self._trajectories = trajectories
        self._item_changed(None)

    @property
    def time_fraction(self):
        return self._time_fraction

    def set_time_fraction(self, fraction):
        self._time_fraction = max(0.0, min(1.0, fraction))
        self._item_changed(None)

    @property
    def show_speed_colors(self):
        return self._show_speed_colors

    def set_show_speed_colors(self, enabled):
        self._show_speed_colors = bool(enabled)
        self._item_changed(None)

    @property
    def show_labels(self):
        return self._show_labels

    def set_show_labels(self, enabled):
        self._show_labels = bool(enabled)
        self._item_changed(None)

    @property
    def line_thickness(self):
        return self._line_thickness

    def set_line_thickness(self, thickness):
        self._line_thickness = max(0.5, min(10.0, float(thickness)))
        self._item_changed(None)
