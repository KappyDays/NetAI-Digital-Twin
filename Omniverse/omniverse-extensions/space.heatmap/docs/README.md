# KKR.SpaceHeatmap

Real-time space congestion heatmap overlay for the Isaac Sim viewport.

## Overview

This extension renders a Green-Yellow-Red heatmap overlay in the Isaac Sim viewport showing space-level density from the Iceberg Lakehouse. It queries the Lakehouse API for congestion summary and spatial grid data, then renders colored cells in the 3D viewport.

## Features

- **Viewport Overlay**: Colored grid cells rendered directly in the 3D scene
- **Auto-Refresh**: Configurable polling interval (5-60 seconds)
- **Grid Resolution**: Adjustable cell density (10x10, 20x20, 50x50)
- **Space Summary**: Per-space congestion breakdown with drill-down details
- **Demo Mode**: Synthetic data fallback when API is unreachable

## API Endpoints

- `GET /api/v1/spaces/congestion/summary` -- Space-level congestion data
- `GET /api/v1/congestion/grid` -- Spatial grid for viewport overlay
- `GET /api/v1/health` -- API health check

## Configuration

Set `LAKEHOUSE_API_URL` environment variable to configure the API endpoint (default: `http://lakehouse-api:8000`).
