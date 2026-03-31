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
Viewport Overlay -- renders congestion heatmap cells in the viewport.

CRITICAL: sc.Rectangle does NOT exist in omni.ui.scene. This module uses
sc.Image with temporary solid-color PNG files instead. PNGs are generated
in pure Python (no PIL/Pillow dependency) and cached to avoid regeneration.
"""

import os
import struct
import tempfile
import zlib

from omni.ui import scene as sc


class HeatmapManipulator(sc.Manipulator):
    """Renders congestion heatmap as colored cells in the viewport."""

    # Cache: {(r, g, b, a): temp_file_path}
    _color_png_cache = {}
    _MAX_CACHE_SIZE = 100

    def on_build(self):
        model = self.model
        if not model or not model.grid or not model.show_grid:
            return

        grid = model.grid
        cell_w = (grid.x_max - grid.x_min) / max(grid.cols, 1)
        cell_h = (grid.y_max - grid.y_min) / max(grid.rows, 1)

        for cell in grid.cells:
            if cell.congestion_level <= 0:
                continue

            r, g, b, a = self._congestion_to_rgba(cell.congestion_level, model.opacity)
            png_path = self._get_color_png(r, g, b, a)

            x = cell.x_center
            y = cell.y_center
            z = 0.01  # Slightly above ground to avoid z-fighting

            with sc.Transform(
                transform=sc.Matrix44.get_translation_matrix(x, y, z)
            ):
                sc.Image(png_path, width=cell_w, height=cell_h)

    def on_model_updated(self, item):
        self.invalidate()

    # -- Color Conversion --------------------------------------------------

    @staticmethod
    def _congestion_to_rgba(level, opacity=0.4):
        """Convert congestion level (0-1) to RGBA. Green -> Yellow -> Red."""
        level = max(0.0, min(1.0, level))
        if level < 0.5:
            # Green to Yellow
            t = level / 0.5
            r = int(255 * t)
            g = 255
            b = 0
        else:
            # Yellow to Red
            t = (level - 0.5) / 0.5
            r = 255
            g = int(255 * (1.0 - t))
            b = 0
        a = int(255 * opacity)
        return r, g, b, a

    # -- PNG Generation & Caching ------------------------------------------

    @classmethod
    def _get_color_png(cls, r, g, b, a):
        """Get or create a small solid-color PNG file. Cached by color."""
        # Quantize to reduce unique keys (round to nearest 8)
        r = (r // 8) * 8
        g = (g // 8) * 8
        b = (b // 8) * 8
        a = (a // 8) * 8
        key = (r, g, b, a)
        if key in cls._color_png_cache:
            path = cls._color_png_cache[key]
            if os.path.exists(path):
                return path

        # Evict oldest if cache full
        if len(cls._color_png_cache) >= cls._MAX_CACHE_SIZE:
            oldest_key = next(iter(cls._color_png_cache))
            oldest_path = cls._color_png_cache.pop(oldest_key)
            try:
                os.unlink(oldest_path)
            except OSError:
                pass

        # Generate minimal 4x4 PNG
        png_data = cls._create_rgba_png(4, 4, r, g, b, a)
        fd, path = tempfile.mkstemp(suffix=".png", prefix="heatmap_")
        os.write(fd, png_data)
        os.close(fd)
        cls._color_png_cache[key] = path
        return path

    @staticmethod
    def _create_rgba_png(width, height, r, g, b, a):
        """Create a minimal RGBA PNG in memory. Pure Python, no dependencies."""
        # PNG signature
        sig = b'\x89PNG\r\n\x1a\n'

        def chunk(chunk_type, data):
            c = chunk_type + data
            crc = zlib.crc32(c) & 0xFFFFFFFF
            return struct.pack('>I', len(data)) + c + struct.pack('>I', crc)

        # IHDR: width, height, bit depth 8, color type 6 (RGBA), compression 0, filter 0, interlace 0
        ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
        ihdr = chunk(b'IHDR', ihdr_data)

        # IDAT: raw pixel data with filter byte per row
        raw_rows = b''
        for _ in range(height):
            raw_rows += b'\x00'  # filter: None
            for _ in range(width):
                raw_rows += bytes([r, g, b, a])
        compressed = zlib.compress(raw_rows)
        idat = chunk(b'IDAT', compressed)

        # IEND
        iend = chunk(b'IEND', b'')

        return sig + ihdr + idat + iend

    # -- Cleanup -----------------------------------------------------------

    @classmethod
    def cleanup_cache(cls):
        """Remove cached PNG temp files."""
        for path in cls._color_png_cache.values():
            try:
                os.unlink(path)
            except OSError:
                pass
        cls._color_png_cache.clear()
