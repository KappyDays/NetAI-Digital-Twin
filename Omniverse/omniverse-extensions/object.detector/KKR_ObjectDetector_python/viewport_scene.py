# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Viewport 2D Overlay -- draws bounding boxes directly on the viewport using omni.ui widgets.

Uses omni.ui.Placer + omni.ui.Rectangle (border) + omni.ui.Label for pixel-accurate
2D bounding box overlay that tracks the viewport frame size.
"""

import omni.ui as ui
import omni.kit.viewport.utility

from .overlay_model import DetectionOverlayModel


class ViewportScene:
    """Manages a 2D bounding box overlay on the active viewport using omni.ui widgets."""

    def __init__(self, ext_id: str):
        self._ext_id = ext_id
        self.model = DetectionOverlayModel()
        self._frame = None
        self._vp_win = None
        self._overlay_container = None

        self._vp_win = omni.kit.viewport.utility.get_active_viewport_window()
        if self._vp_win is None:
            raise RuntimeError("No active viewport window")

        # Get a frame in the viewport window for our 2D overlay
        self._frame = self._vp_win.get_frame(ext_id)

        # Subscribe to model changes to rebuild overlay
        self.model.add_change_callback(self._rebuild_overlay)

    def _rebuild_overlay(self):
        """Rebuild the 2D overlay when detection data changes."""
        if self._frame is None:
            return

        detections = self.model.detections
        img_w = self.model.image_width
        img_h = self.model.image_height

        # Get viewport frame dimensions
        frame_w = self._frame.computed_width
        frame_h = self._frame.computed_height
        if frame_w <= 0 or frame_h <= 0:
            frame_w = 1280
            frame_h = 720

        # Build overlay UI
        self._frame.clear()

        if not detections:
            return

        with self._frame:
            with ui.ZStack():
                for det in detections:
                    # Map pixel coords to viewport frame coords
                    x1 = (det.x1 / img_w) * frame_w
                    y1 = (det.y1 / img_h) * frame_h
                    x2 = (det.x2 / img_w) * frame_w
                    y2 = (det.y2 / img_h) * frame_h
                    bw = max(x2 - x1, 1)
                    bh = max(y2 - y1, 1)

                    color = _get_class_color(det.class_name)
                    label = f"{det.class_name} {det.confidence:.0%}"

                    # Bounding box (border-only rectangle)
                    with ui.Placer(offset_x=x1, offset_y=y1):
                        ui.Rectangle(
                            width=bw, height=bh,
                            style={
                                "background_color": 0x00000000,
                                "border_color": color,
                                "border_width": 3,
                                "border_radius": 0,
                            },
                        )

                    # Label background + text
                    with ui.Placer(offset_x=x1, offset_y=max(y1 - 20, 0)):
                        with ui.ZStack(width=0, height=0):
                            ui.Rectangle(
                                width=len(label) * 8 + 10, height=20,
                                style={"background_color": color, "border_radius": 2},
                            )
                            ui.Label(
                                label,
                                style={"color": 0xFF000000, "font_size": 13},
                                width=len(label) * 8 + 10, height=20,
                                alignment=ui.Alignment.CENTER,
                            )

    def destroy(self):
        """Clean up the overlay."""
        if self._frame is not None:
            self._frame.clear()
            self._frame = None
        self.model = None


# ── Color helpers ────────────────────────────────────────────────────

_CLASS_COLORS = {
    "person": 0xFF4444FF,
    "chair": 0xFF44FF44,
    "couch": 0xFFFF8844,
    "bed": 0xFF4488FF,
    "dining table": 0xFF44FFFF,
    "tv": 0xFFFF44FF,
    "laptop": 0xFFFFFF44,
    "bench": 0xFF64C8FF,
    "bottle": 0xFF4488AA,
    "cup": 0xFFAAAAFF,
    "book": 0xFFAAFFAA,
}
_DEFAULT_COLOR = 0xFF00CCFF


def _get_class_color(class_name: str) -> int:
    return _CLASS_COLORS.get(class_name, _DEFAULT_COLOR)
