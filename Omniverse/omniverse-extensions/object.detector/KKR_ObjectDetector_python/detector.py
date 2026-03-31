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
YOLOv8 wrapper for object detection.

Uses ultralytics (bundled in Isaac Sim). Model is loaded lazily on first
inference call. All public methods except detect() are main-thread-safe.
detect() MUST be called from a background thread via run_in_executor.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class Detection:
    """Single detection result in pixel coordinates."""

    x1: float
    y1: float
    x2: float
    y2: float
    class_name: str
    confidence: float
    class_id: int


class ObjectDetector:
    """YOLOv8 inference wrapper with lazy model loading."""

    def __init__(self, model_path: str = "yolov8s.pt", confidence: float = 0.5, device: str = "cuda"):
        self._model_path = model_path
        self._confidence = confidence
        self._device = device
        self._model = None  # lazy load

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load_model(self):
        """Load the YOLO model. Safe to call from background thread."""
        from ultralytics import YOLO

        self._model = YOLO(self._model_path)

    def detect(self, rgb_array: np.ndarray) -> list:
        """Run inference on an RGB numpy array. MUST be called from background thread only.

        Args:
            rgb_array: HxWx3 uint8 numpy array (RGB).

        Returns:
            List of Detection objects.
        """
        if not self.is_loaded:
            self.load_model()

        results = self._model(rgb_array, conf=self._confidence, device=self._device, verbose=False)
        detections = []
        for r in results:
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                detections.append(
                    Detection(
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2),
                        class_name=r.names[int(box.cls[0])],
                        confidence=float(box.conf[0]),
                        class_id=int(box.cls[0]),
                    )
                )
        return detections

    def unload(self):
        """Release the model from memory."""
        self._model = None

    def set_confidence(self, conf: float):
        self._confidence = max(0.05, min(1.0, conf))

    def set_model_path(self, path: str):
        self._model_path = path
