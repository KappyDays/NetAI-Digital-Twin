# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Data model for detection overlay. Holds detection results and notifies
the viewport overlay via a simple callback when data changes.
"""


class DetectionOverlayModel:
    """Stores detection results and image dimensions for the viewport overlay."""

    def __init__(self):
        self._detections = []
        self._image_width = 1
        self._image_height = 1
        self._change_callback = None

    @property
    def detections(self):
        return self._detections

    @property
    def image_width(self):
        return self._image_width

    @property
    def image_height(self):
        return self._image_height

    def add_change_callback(self, fn):
        """Register a callback to be called when detections change."""
        self._change_callback = fn

    def set_detections(self, detections, img_w, img_h):
        """Update detections and image dimensions, then signal a redraw."""
        self._detections = detections
        self._image_width = max(img_w, 1)
        self._image_height = max(img_h, 1)
        if self._change_callback:
            self._change_callback()

    def clear(self):
        """Remove all detections and signal a redraw."""
        self._detections = []
        if self._change_callback:
            self._change_callback()
