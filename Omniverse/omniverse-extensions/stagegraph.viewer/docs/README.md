# KKR.StageGraph

Interactive TreeView visualization of the current USD Stage hierarchy with type-based color coding, viewport selection, and Iceberg Lakehouse diff.

## Features

- **Stage Hierarchy Tree**: Scans the live USD Stage and displays all prims in a collapsible TreeView.
- **Type Color Coding**: Each prim type (Mesh, Xform, Camera, Light, etc.) gets a distinct color indicator.
- **Viewport Selection**: Click any tree row to select the corresponding prim in the Isaac Sim viewport.
- **Type Distribution**: Proportional bar chart showing prim type counts.
- **Iceberg Diff**: Compare the live stage against prims stored in the Iceberg Lakehouse catalog.

## Configuration

Set `LAKEHOUSE_API_URL` environment variable to point to the FastAPI middleware (default: `http://lakehouse-api:8000`).
