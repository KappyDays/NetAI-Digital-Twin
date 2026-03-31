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
Overlay Model -- data model for the heatmap viewport overlay.

Holds the current HeatmapGrid and SpaceCongestion list, and notifies
the viewport manipulator when data changes via _item_changed().
"""

from omni.ui import scene as sc


class HeatmapOverlayModel(sc.AbstractManipulatorModel):
    """Data model for heatmap overlay."""

    def __init__(self):
        super().__init__()
        self._grid = None  # HeatmapGrid from data_fetcher
        self._spaces = []  # list of SpaceCongestion
        self._show_grid = True
        self._opacity = 0.4

    # -- Grid property -----------------------------------------------------

    @property
    def grid(self):
        return self._grid

    def set_grid(self, grid):
        self._grid = grid
        self._item_changed(None)

    # -- Spaces property ---------------------------------------------------

    @property
    def spaces(self):
        return self._spaces

    def set_spaces(self, spaces):
        self._spaces = spaces
        self._item_changed(None)

    # -- Show grid toggle --------------------------------------------------

    @property
    def show_grid(self):
        return self._show_grid

    def set_show_grid(self, value: bool):
        self._show_grid = value
        self._item_changed(None)

    # -- Opacity -----------------------------------------------------------

    @property
    def opacity(self):
        return self._opacity

    def set_opacity(self, value: float):
        self._opacity = max(0.0, min(1.0, value))
        self._item_changed(None)
