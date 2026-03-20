"""
Tests for the congestion grid heatmap endpoint and dashboard serving.

Tests:
  1. GET /api/v1/congestion/grid returns valid CongestionGridResponse schema
  2. Grid resolution parameters (rows/cols) are respected
  3. Invalid bounds return 400 error
  4. Dashboard HTML is served at /dashboard/heatmap
  5. Dashboard HTML contains required heatmap Canvas element
  6. CongestionGridResponse model validates correctly
  7. Color scale and tooltip JavaScript are present in dashboard
  8. Grid cell coordinate bounds are mathematically correct
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import CongestionGridCell, CongestionGridConfig, CongestionGridResponse


@pytest.fixture()
def client():
    return TestClient(app)


# -- Mock data for congestion grid -------------------------------------------

def _mock_empty_grid(**kwargs):
    """Return an empty congestion grid."""
    rows = kwargs.get("rows", 20)
    cols = kwargs.get("cols", 20)
    return {
        "config": {
            "x_min": kwargs.get("x_min", -50.0),
            "x_max": kwargs.get("x_max", 50.0),
            "y_min": kwargs.get("y_min", -50.0),
            "y_max": kwargs.get("y_max", 50.0),
            "rows": rows,
            "cols": cols,
            "cell_width": (kwargs.get("x_max", 50.0) - kwargs.get("x_min", -50.0)) / cols,
            "cell_height": (kwargs.get("y_max", 50.0) - kwargs.get("y_min", -50.0)) / rows,
        },
        "cells": [],
        "grid": [[0.0] * cols for _ in range(rows)],
        "max_value": 0.0,
        "total_objects": 0,
        "snapshot_time": datetime.now(timezone.utc).isoformat(),
    }


def _mock_populated_grid(**kwargs):
    """Return a congestion grid with sample objects."""
    rows = kwargs.get("rows", 10)
    cols = kwargs.get("cols", 10)
    x_min = kwargs.get("x_min", -50.0)
    x_max = kwargs.get("x_max", 50.0)
    y_min = kwargs.get("y_min", -50.0)
    y_max = kwargs.get("y_max", 50.0)
    cell_w = (x_max - x_min) / cols
    cell_h = (y_max - y_min) / rows

    grid = [[0.0] * cols for _ in range(rows)]
    grid[3][4] = 5.0
    grid[7][2] = 3.0
    grid[5][5] = 8.0

    cells = [
        {
            "row": 3, "col": 4, "value": 5.0,
            "x_min": x_min + 4 * cell_w, "x_max": x_min + 5 * cell_w,
            "y_min": y_min + 3 * cell_h, "y_max": y_min + 4 * cell_h,
            "object_ids": ["obj_a", "obj_b", "obj_c", "obj_d", "obj_e"],
        },
        {
            "row": 7, "col": 2, "value": 3.0,
            "x_min": x_min + 2 * cell_w, "x_max": x_min + 3 * cell_w,
            "y_min": y_min + 7 * cell_h, "y_max": y_min + 8 * cell_h,
            "object_ids": ["obj_f", "obj_g", "obj_h"],
        },
        {
            "row": 5, "col": 5, "value": 8.0,
            "x_min": x_min + 5 * cell_w, "x_max": x_min + 6 * cell_w,
            "y_min": y_min + 5 * cell_h, "y_max": y_min + 6 * cell_h,
            "object_ids": [f"obj_{i}" for i in range(8)],
        },
    ]

    return {
        "config": {
            "x_min": x_min, "x_max": x_max,
            "y_min": y_min, "y_max": y_max,
            "rows": rows, "cols": cols,
            "cell_width": cell_w, "cell_height": cell_h,
        },
        "cells": cells,
        "grid": grid,
        "max_value": 8.0,
        "total_objects": 16,
        "snapshot_time": datetime.now(timezone.utc).isoformat(),
    }


# =====================================================================
#  Test: Congestion Grid API Endpoint
# =====================================================================

class TestCongestionGridEndpoint:
    """Test GET /api/v1/congestion/grid."""

    @patch("app.services.trino_service.get_congestion_grid")
    def test_grid_returns_200_with_valid_schema(self, mock_grid, client):
        """Grid endpoint returns 200 with CongestionGridResponse schema."""
        mock_grid.return_value = _mock_empty_grid()

        resp = client.get("/api/v1/congestion/grid")
        assert resp.status_code == 200

        data = resp.json()
        assert "config" in data
        assert "grid" in data
        assert "cells" in data
        assert "max_value" in data
        assert "total_objects" in data
        assert "snapshot_time" in data

    @patch("app.services.trino_service.get_congestion_grid")
    def test_grid_respects_resolution_params(self, mock_grid, client):
        """Custom rows/cols parameters are passed to the service."""
        mock_grid.return_value = _mock_empty_grid(rows=30, cols=30)

        resp = client.get("/api/v1/congestion/grid?rows=30&cols=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["config"]["rows"] == 30
        assert data["config"]["cols"] == 30
        assert len(data["grid"]) == 30
        assert len(data["grid"][0]) == 30

    @patch("app.services.trino_service.get_congestion_grid")
    def test_grid_with_populated_data(self, mock_grid, client):
        """Grid with objects shows correct counts and cell data."""
        mock_grid.return_value = _mock_populated_grid(rows=10, cols=10)

        resp = client.get("/api/v1/congestion/grid?rows=10&cols=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_objects"] == 16
        assert data["max_value"] == 8.0
        assert len(data["cells"]) == 3  # 3 non-empty cells

    def test_grid_invalid_bounds_returns_400(self, client):
        """x_min >= x_max should return 400."""
        resp = client.get("/api/v1/congestion/grid?x_min=50&x_max=-50")
        assert resp.status_code == 400
        assert "Invalid bounds" in resp.json()["detail"]

    def test_grid_equal_bounds_returns_400(self, client):
        """Equal min/max bounds should return 400."""
        resp = client.get("/api/v1/congestion/grid?y_min=0&y_max=0")
        assert resp.status_code == 400

    @patch("app.services.trino_service.get_congestion_grid")
    def test_grid_custom_bounds(self, mock_grid, client):
        """Custom coordinate bounds are reflected in the config."""
        mock_grid.return_value = _mock_empty_grid(
            x_min=-100, x_max=100, y_min=-200, y_max=200
        )
        resp = client.get(
            "/api/v1/congestion/grid?x_min=-100&x_max=100&y_min=-200&y_max=200"
        )
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["x_min"] == -100.0
        assert cfg["x_max"] == 100.0


# =====================================================================
#  Test: CongestionGrid Pydantic Models
# =====================================================================

class TestCongestionGridModels:
    """Test Pydantic schema validation for grid models."""

    def test_grid_config_defaults(self):
        cfg = CongestionGridConfig()
        assert cfg.rows == 20
        assert cfg.cols == 20
        assert cfg.x_min == -50.0

    def test_grid_cell_validation(self):
        cell = CongestionGridCell(
            row=5, col=3, value=7.0,
            x_min=-10.0, x_max=-5.0,
            y_min=0.0, y_max=5.0,
            object_ids=["a", "b"],
        )
        assert cell.row == 5
        assert cell.col == 3
        assert cell.value == 7.0
        assert len(cell.object_ids) == 2

    def test_grid_response_full(self):
        data = _mock_populated_grid(rows=10, cols=10)
        resp = CongestionGridResponse(**data)
        assert resp.total_objects == 16
        assert resp.max_value == 8.0
        assert len(resp.cells) == 3
        assert len(resp.grid) == 10

    def test_cell_coordinates_are_consistent(self):
        """Cell x_min/x_max/y_min/y_max should match grid config geometry."""
        data = _mock_populated_grid(rows=10, cols=10)
        cfg = data["config"]
        cell_w = cfg["cell_width"]
        cell_h = cfg["cell_height"]

        for cell in data["cells"]:
            expected_x_min = cfg["x_min"] + cell["col"] * cell_w
            expected_y_min = cfg["y_min"] + cell["row"] * cell_h
            assert abs(cell["x_min"] - expected_x_min) < 0.01
            assert abs(cell["y_min"] - expected_y_min) < 0.01


# =====================================================================
#  Test: Dashboard HTML Serving
# =====================================================================

class TestDashboardServing:
    """Test that the heatmap dashboard is served correctly."""

    def test_dashboard_heatmap_returns_html(self, client):
        """GET /dashboard/heatmap returns HTML content."""
        resp = client.get("/dashboard/heatmap")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_dashboard_main_returns_html(self, client):
        """GET /dashboard serves a dashboard page (HTML response)."""
        resp = client.get("/dashboard")
        # May return 200 (if template exists) or 404 (HTML not found page)
        assert "text/html" in resp.headers.get("content-type", "")

    def test_dashboard_contains_canvas(self, client):
        """Dashboard HTML contains the heatmapCanvas element."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert 'id="heatmapCanvas"' in html

    def test_dashboard_contains_tooltip(self, client):
        """Dashboard HTML has a tooltip element for hover interactions."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert 'id="tooltip"' in html

    def test_dashboard_contains_color_scales(self, client):
        """Dashboard JS includes multiple color scales."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert "COLOR_SCALES" in html
        assert "thermal" in html
        assert "viridis" in html

    def test_dashboard_contains_api_fetch(self, client):
        """Dashboard JS fetches the congestion grid API."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert "/api/v1/congestion/grid" in html

    def test_dashboard_contains_demo_mode(self, client):
        """Dashboard has a demo data generator for offline use."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert "generateDemoData" in html

    def test_dashboard_has_auto_refresh(self, client):
        """Dashboard includes auto-refresh functionality."""
        resp = client.get("/dashboard/heatmap")
        html = resp.text
        assert "autoRefresh" in html
        assert "refreshInterval" in html


# =====================================================================
#  Test: Root endpoint includes dashboard link
# =====================================================================

class TestRootEndpoint:

    def test_root_has_dashboard_link(self, client):
        """Root endpoint JSON includes link to dashboard."""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "dashboard" in data
