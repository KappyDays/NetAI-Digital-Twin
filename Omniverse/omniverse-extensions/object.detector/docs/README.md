# KKR.ObjectDetector

Real-time object detection in Isaac Sim viewport using YOLOv8.

## Features

- Captures frames from a Camera Prim in the stage
- Runs YOLOv8 inference (bundled in Isaac Sim via ultralytics)
- Overlays bounding boxes with class labels in the viewport
- Single-shot and periodic auto-detect modes
- Configurable confidence threshold and detection interval

## Usage

1. Enable the extension in Isaac Sim Extension Manager
2. Open the panel from the menu bar
3. Set the Camera Prim path (default: `/World/Camera`)
4. Click **Initialize Camera**
5. Click **Detect Now** or enable **Auto-Detect**

## Requirements

- Isaac Sim with `ultralytics` (bundled)
- A Camera Prim in the USD stage
- Simulation must be running for camera frame capture
