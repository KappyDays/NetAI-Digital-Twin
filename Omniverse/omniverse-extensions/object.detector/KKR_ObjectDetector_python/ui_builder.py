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
Panel UI for the Object Detector extension.

Provides controls for:
    - Camera prim path configuration and initialization
    - YOLO model path and confidence threshold
    - Single-shot and auto-detect modes
    - Detection results display with class counts
"""

import asyncio
import time
import traceback
from collections import Counter

import omni
import omni.kit.app
import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    Button,
    CheckBox,
    CollapsableFrame,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import get_style

from .detector import ObjectDetector


# Color palette for results list (0xAABBGGRR format)
_RESULT_COLORS = [
    0xFFFF4444, 0xFF44FF44, 0xFF4488FF, 0xFF44FFFF,
    0xFFFF44FF, 0xFFFFFF44, 0xFF8844FF, 0xFF44FFAA,
]


class UIBuilder:
    """Panel UI for the Object Detector extension."""

    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []
        self._detector = ObjectDetector()
        self._overlay_model = None  # Set by extension.py via set_overlay_model()
        self._inference_lock = asyncio.Lock()  # prevent concurrent YOLO calls
        self._auto_detect_running = False
        self._auto_detect_task = None
        self._camera = None
        self._refresh_interval = 3.0  # seconds

    def set_overlay_model(self, model):
        """Called by extension.py to share the viewport overlay model."""
        self._overlay_model = model

    # =========================================================================
    #  Automatic callbacks wired by extension.py
    # =========================================================================

    def on_menu_callback(self):
        pass

    def on_timeline_event(self, event):
        pass

    def on_physics_step(self, step):
        pass

    def on_stage_event(self, event):
        pass

    def cleanup(self):
        """Clean up panel UI elements. Does NOT destroy viewport overlay."""
        self._auto_detect_running = False
        if self._auto_detect_task:
            self._auto_detect_task.cancel()
            self._auto_detect_task = None
        for ui_elem in self.wrapped_ui_elements:
            ui_elem.cleanup()

    def build_ui(self):
        self._create_status_frame()
        self._create_camera_config_frame()
        self._create_model_config_frame()
        self._create_detection_controls_frame()
        self._create_results_frame()

    # =========================================================================
    #  Frame 1: Status / Log
    # =========================================================================

    def _create_status_frame(self):
        self._status_frame = CollapsableFrame("Status / Log", collapsed=False)
        with self._status_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._status_field = TextBlock(
                    "Last Operation",
                    num_lines=6,
                    tooltip="Operation results and logs",
                    include_copy_button=True,
                )

    def _set_status(self, message: str):
        self._status_field.set_text(message)

    # =========================================================================
    #  Frame 2: Camera Configuration
    # =========================================================================

    def _create_camera_config_frame(self):
        frame = CollapsableFrame("Camera Configuration", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Set the Camera Prim path in the stage.\n"
                    "The camera must exist before initialization.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._camera_path_field = StringField(
                    "Camera Prim Path",
                    default_value="/World/Camera",
                    tooltip="USD path to the Camera prim (e.g. /World/Camera)",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=lambda _: None,
                )
                self.wrapped_ui_elements.append(self._camera_path_field)

                self._init_camera_btn = Button(
                    "Initialize Camera",
                    "Initialize Camera",
                    tooltip="Create and initialize the Camera sensor at the given prim path",
                    on_click_fn=self._on_init_camera,
                )
                self.wrapped_ui_elements.append(self._init_camera_btn)

    def _on_init_camera(self):
        self._set_status("Initializing camera...")
        asyncio.ensure_future(self._init_camera())

    async def _init_camera(self):
        try:
            import isaacsim.sensors.camera as cam_module

            prim_path = self._camera_path_field.get_value()
            self._camera = cam_module.Camera(
                prim_path=prim_path,
                resolution=(640, 480),
            )
            self._camera.initialize()
            await omni.kit.app.get_app().next_update_async()  # wait for first render frame
            self._set_status(f"[OK] Camera initialized at {prim_path} (640x480)")
        except Exception as e:
            self._camera = None
            self._set_status(f"[ERROR] Camera initialization failed: {e}\n{traceback.format_exc()}")

    # =========================================================================
    #  Frame 3: Model Configuration
    # =========================================================================

    def _create_model_config_frame(self):
        frame = CollapsableFrame("Model Configuration", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label(
                    "Configure the YOLOv8 model for detection.\n"
                    "Default model (yolov8s.pt) will be downloaded on first use if not cached.",
                    word_wrap=True,
                    style={"color": 0xFFAAAAAA},
                )

                self._model_path_field = StringField(
                    "Model Path",
                    default_value="yolov8s.pt",
                    tooltip="Path to YOLO model weights (e.g. yolov8s.pt, yolov8m.pt)",
                    read_only=False,
                    multiline_okay=False,
                    on_value_changed_fn=self._on_model_path_changed,
                )
                self.wrapped_ui_elements.append(self._model_path_field)

                # Confidence threshold slider
                ui.Label("Confidence Threshold", style={"color": 0xFFCCCCCC})
                self._confidence_slider = ui.FloatSlider(min=0.1, max=1.0, step=0.05)
                self._confidence_slider.model.set_value(0.5)
                self._confidence_slider.model.add_value_changed_fn(self._on_confidence_changed)

                with ui.HStack(spacing=5, height=0):
                    self._load_model_btn = Button(
                        "Load Model",
                        "Load Model",
                        tooltip="Pre-load the YOLO model into memory",
                        on_click_fn=self._on_load_model,
                    )
                    self.wrapped_ui_elements.append(self._load_model_btn)

                    self._unload_model_btn = Button(
                        "Unload Model",
                        "Unload Model",
                        tooltip="Release the YOLO model from memory",
                        on_click_fn=self._on_unload_model,
                    )
                    self.wrapped_ui_elements.append(self._unload_model_btn)

    def _on_model_path_changed(self, value):
        path = value.get_value_as_string() if hasattr(value, "get_value_as_string") else str(value)
        self._detector.set_model_path(path.strip())
        self._set_status(f"Model path updated: {path.strip()}")

    def _on_confidence_changed(self, model):
        conf = model.get_value_as_float()
        self._detector.set_confidence(conf)

    def _on_load_model(self):
        self._set_status("Loading YOLO model (this may take a few seconds)...")

        async def _async_load():
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._detector.load_model)
                self._set_status("[OK] YOLO model loaded successfully")
            except Exception as e:
                self._set_status(f"[ERROR] Model loading failed: {e}\n{traceback.format_exc()}")

        asyncio.ensure_future(_async_load())

    def _on_unload_model(self):
        self._detector.unload()
        self._set_status("[OK] YOLO model unloaded")

    # =========================================================================
    #  Frame 4: Detection Controls
    # =========================================================================

    def _create_detection_controls_frame(self):
        frame = CollapsableFrame("Detection Controls", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                with ui.HStack(spacing=5, height=0):
                    self._detect_now_btn = Button(
                        "Detect Now",
                        "Detect Now",
                        tooltip="Run a single detection on the current camera frame",
                        on_click_fn=self._on_detect_now,
                    )
                    self.wrapped_ui_elements.append(self._detect_now_btn)

                    self._clear_overlay_btn = Button(
                        "Clear Overlay",
                        "Clear Overlay",
                        tooltip="Remove all bounding boxes from the viewport",
                        on_click_fn=self._on_clear_overlay,
                    )
                    self.wrapped_ui_elements.append(self._clear_overlay_btn)

                ui.Spacer(height=5)

                # Auto-detect toggle
                with ui.HStack(spacing=5, height=0):
                    self._auto_detect_cb = ui.CheckBox(width=20)
                    self._auto_detect_cb.model.set_value(False)
                    self._auto_detect_cb.model.add_value_changed_fn(self._on_auto_detect_toggled)
                    ui.Label("Auto-Detect (periodic)", word_wrap=False)

                # Interval slider
                ui.Label("Refresh Interval (seconds)", style={"color": 0xFFCCCCCC})
                self._interval_slider = ui.FloatSlider(min=1.0, max=10.0, step=0.5)
                self._interval_slider.model.set_value(3.0)
                self._interval_slider.model.add_value_changed_fn(self._on_interval_changed)

    def _on_detect_now(self):
        asyncio.ensure_future(self._run_detection())

    def _on_clear_overlay(self):
        """Clear all bounding boxes from the viewport and panel preview."""
        if self._overlay_model is not None:
            self._overlay_model.clear()
        if hasattr(self, "_preview_image") and self._preview_image is not None:
            self._preview_image.source_url = ""
        if hasattr(self, "_results_summary"):
            self._results_summary.set_text("  (cleared)")
        if hasattr(self, "_results_container"):
            self._results_container.clear()
        self._set_status("[OK] Overlay cleared.")

    def _on_auto_detect_toggled(self, model):
        enabled = model.get_value_as_bool()
        if enabled:
            self._auto_detect_running = True
            self._auto_detect_task = asyncio.ensure_future(self._auto_detect_loop())
            self._set_status("[OK] Auto-detect started")
        else:
            self._auto_detect_running = False
            if self._auto_detect_task:
                self._auto_detect_task.cancel()
                self._auto_detect_task = None
            self._set_status("[OK] Auto-detect stopped")

    def _on_interval_changed(self, model):
        self._refresh_interval = model.get_value_as_float()

    # =========================================================================
    #  Detection Pipeline
    # =========================================================================

    async def _run_detection(self):
        """Run a single detection cycle: capture frame, infer, update overlay."""
        async with self._inference_lock:
            if self._camera is None:
                self._set_status("[WARN] Camera not initialized. Please initialize camera first.")
                return
            try:
                loop = asyncio.get_running_loop()

                # Capture frame (must be on main thread for Camera API)
                import numpy as np
                rgba = self._camera.get_rgba(device="cpu")
                if rgba is None or (isinstance(rgba, np.ndarray) and rgba.size == 0):
                    self._set_status(
                        "[WARN] Camera returned empty frame. "
                        "Press PLAY in the timeline first, then try again."
                    )
                    return
                # Camera may return flat 1D array or (H,W,4) — handle both
                if isinstance(rgba, np.ndarray) and rgba.ndim == 1:
                    res = self._camera.get_resolution()
                    if res is not None:
                        h, w = int(res[1]), int(res[0])
                        if rgba.size == h * w * 4:
                            rgba = rgba.reshape(h, w, 4)
                        else:
                            self._set_status(f"[WARN] Unexpected array size {rgba.size} for {w}x{h}. Press PLAY first.")
                            return
                    else:
                        self._set_status("[WARN] Cannot determine camera resolution. Press PLAY first.")
                        return
                rgb = rgba[:, :, :3]  # RGBA -> RGB
                img_h, img_w = rgb.shape[:2]

                t0 = time.monotonic()

                # YOLO inference on background thread
                rgb_copy = rgb.copy()
                detections = await loop.run_in_executor(None, lambda: self._detector.detect(rgb_copy))

                elapsed_ms = (time.monotonic() - t0) * 1000

                # Draw bounding boxes on the frame using cv2
                annotated = self._draw_boxes_on_frame(rgb.copy(), detections)

                # Save annotated image to temp file for display
                import cv2
                import tempfile
                import os
                # Use alternating files to force omni.ui.Image to reload
                if not hasattr(self, "_preview_idx"):
                    self._preview_idx = 0
                    self._preview_paths = []
                    for i in range(2):
                        fd, p = tempfile.mkstemp(suffix=f"_{i}.png", prefix="detect_")
                        os.close(fd)
                        self._preview_paths.append(p)
                self._preview_idx = 1 - self._preview_idx
                path = self._preview_paths[self._preview_idx]
                cv2.imwrite(path, cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))

                # Update preview image in panel (alternate path forces reload)
                if hasattr(self, "_preview_image") and self._preview_image is not None:
                    self._preview_image.source_url = path

                # Update viewport overlay model (keep for future use)
                if self._overlay_model is not None:
                    self._overlay_model.set_detections(detections, img_w, img_h)

                # Update results panel
                self._update_results_panel(detections)
                self._set_status(
                    f"[OK] Detected {len(detections)} objects "
                    f"({img_w}x{img_h}, {elapsed_ms:.0f}ms inference)"
                )
            except Exception as e:
                self._set_status(f"[ERROR] Detection failed: {e}\n{traceback.format_exc()}")

    async def _auto_detect_loop(self):
        """Periodic detection loop using wall-clock timing."""
        while self._auto_detect_running:
            await self._run_detection()
            # Wall-clock wait using app frame ticks (non-blocking)
            start = time.monotonic()
            while time.monotonic() - start < self._refresh_interval:
                if not self._auto_detect_running:
                    return
                await omni.kit.app.get_app().next_update_async()

    # =========================================================================
    #  Frame 5: Results Display
    # =========================================================================

    def _create_results_frame(self):
        self._results_frame = CollapsableFrame("Detection Results", collapsed=False)
        with self._results_frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                # Preview image with bounding boxes
                ui.Label("Detection Preview", style={"color": 0xFFCCCCCC})
                self._preview_image = ui.Image(
                    "",
                    height=300,
                    fill_policy=ui.FillPolicy.PRESERVE_ASPECT_FIT,
                    style={"background_color": 0xFF111111},
                )

                self._results_summary = TextBlock(
                    "Class Summary",
                    num_lines=4,
                    tooltip="Count of detected objects per class",
                    include_copy_button=True,
                )

                ui.Label("Individual Detections", style={"color": 0xFFCCCCCC})
                self._results_scroll = ui.ScrollingFrame(
                    height=150,
                    style={"background_color": 0xFF1A1A1A},
                )
                with self._results_scroll:
                    self._results_container = ui.VStack(spacing=2, height=0)

    def _update_results_panel(self, detections):
        """Update the results panel with detection data."""
        # Class count summary
        counts = Counter(d.class_name for d in detections)
        if counts:
            summary_lines = [f"  {name}: {count}" for name, count in counts.most_common()]
            self._results_summary.set_text("\n".join(summary_lines))
        else:
            self._results_summary.set_text("  No detections")

        # Individual detection list
        self._results_container.clear()
        with self._results_container:
            for idx, det in enumerate(detections):
                color = _RESULT_COLORS[idx % len(_RESULT_COLORS)]
                with ui.HStack(spacing=5, height=0):
                    ui.Label(
                        f"[{idx}] {det.class_name} ({det.confidence:.0%}) "
                        f"  box=({det.x1:.0f},{det.y1:.0f})-({det.x2:.0f},{det.y2:.0f})",
                        word_wrap=False,
                        style={"color": color},
                    )

    def _draw_boxes_on_frame(self, frame, detections):
        """Draw bounding boxes and labels on the frame using cv2."""
        import cv2
        import numpy as np

        # BGR color palette matching CLASS_COLORS
        COLORS = {
            "person": (68, 68, 255),
            "chair": (68, 255, 68),
            "couch": (255, 136, 68),
            "bed": (68, 136, 255),
            "dining table": (68, 255, 255),
            "tv": (255, 68, 255),
            "laptop": (255, 255, 68),
            "bench": (100, 200, 255),
            "bottle": (68, 136, 170),
            "cup": (170, 170, 255),
            "book": (170, 255, 170),
        }
        DEFAULT = (0, 204, 255)

        # Scale up small images for better visibility
        h, w = frame.shape[:2]
        scale = max(1, 512 // max(h, w))
        if scale > 1:
            frame = cv2.resize(frame, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)

        for det in detections:
            x1 = int(det.x1 * scale)
            y1 = int(det.y1 * scale)
            x2 = int(det.x2 * scale)
            y2 = int(det.y2 * scale)
            color = COLORS.get(det.class_name, DEFAULT)
            label = f"{det.class_name} {det.confidence:.0%}"

            # Draw box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            # Draw label background
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(frame, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return frame
