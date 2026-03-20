"""
Tests for the congestion timeline chart component.

Covers:
  1. GET /api/v1/congestion/timeseries endpoint (query parameters)
  2. GET /api/v1/dashboard endpoint (HTML page serving)
  3. Chart.js integration (CDN script references in HTML)
  4. Zoom plugin inclusion
  5. Time range presets in the UI
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════
#  Dashboard HTML endpoint
# ═══════════════════════════════════════════════════════════════════

class TestDashboardPage:
    """Test the dashboard HTML page serving."""

    def test_dashboard_returns_html(self):
        """GET /api/v1/dashboard should return 200 with HTML content."""
        resp = client.get("/api/v1/dashboard/timeline")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_chart_js(self):
        """Dashboard HTML must include Chart.js CDN reference."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "chart.js" in body.lower() or "Chart" in body

    def test_dashboard_contains_zoom_plugin(self):
        """Dashboard HTML must include chartjs-plugin-zoom for zoom/pan."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "chartjs-plugin-zoom" in body

    def test_dashboard_contains_date_adapter(self):
        """Dashboard HTML must include a date adapter for time scale."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "chartjs-adapter-date-fns" in body

    def test_dashboard_contains_time_presets(self):
        """Dashboard should have time range preset buttons."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "5m" in body
        assert "1h" in body
        assert "24h" in body
        assert "7d" in body

    def test_dashboard_contains_zoom_controls(self):
        """Dashboard should have zoom reset button and help text."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "resetZoom" in body or "Reset Zoom" in body
        assert "zoom" in body.lower()

    def test_dashboard_contains_auto_refresh(self):
        """Dashboard should have auto-refresh toggle."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "autoRefresh" in body or "auto-refresh" in body.lower() or "Auto-refresh" in body

    def test_dashboard_contains_canvas(self):
        """Dashboard must have a canvas element for Chart.js."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "<canvas" in body
        assert "congestionChart" in body

    def test_dashboard_api_endpoint_reference(self):
        """Dashboard JS should reference the timeseries API endpoint."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "congestion/timeseries" in body

    def test_dashboard_contains_bucket_selector(self):
        """Dashboard should have bucket size selector."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "bucketSeconds" in body or "bucket_seconds" in body

    def test_dashboard_contains_space_filter(self):
        """Dashboard should have space filter dropdown."""
        resp = client.get("/api/v1/dashboard/timeline")
        body = resp.text
        assert "spaceFilter" in body or "space_id" in body


# ═══════════════════════════════════════════════════════════════════
#  Congestion Timeseries GET Endpoint
# ═══════════════════════════════════════════════════════════════════

class TestCongestionTimeseriesEndpoint:
    """Test GET /api/v1/congestion/timeseries endpoint."""

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_returns_200(self, mock_ts):
        """Basic call with defaults should return 200."""
        mock_ts.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 5],
                ["Room_A", "2026-03-19T10:01:00", 3],
            ],
            "row_count": 2,
        }
        resp = client.get("/api/v1/congestion/timeseries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["row_count"] == 2
        assert data["columns"] == ["space_id", "time_bucket", "object_count"]

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_with_space_filter(self, mock_ts):
        """Should pass space_id query parameter to the service."""
        mock_ts.return_value = {"columns": [], "rows": [], "row_count": 0}
        resp = client.get("/api/v1/congestion/timeseries?space_id=Room_A")
        assert resp.status_code == 200
        mock_ts.assert_called_once()
        call_kwargs = mock_ts.call_args
        assert call_kwargs.kwargs.get("space_id") == "Room_A" or \
               (call_kwargs.args and call_kwargs.args[0] == "Room_A")

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_with_time_range(self, mock_ts):
        """Should accept start_time and end_time ISO 8601 parameters."""
        mock_ts.return_value = {"columns": [], "rows": [], "row_count": 0}
        resp = client.get(
            "/api/v1/congestion/timeseries"
            "?start_time=2026-03-19T00:00:00"
            "&end_time=2026-03-19T12:00:00"
        )
        assert resp.status_code == 200

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_with_bucket_seconds(self, mock_ts):
        """Should accept custom bucket_seconds parameter."""
        mock_ts.return_value = {"columns": [], "rows": [], "row_count": 0}
        resp = client.get("/api/v1/congestion/timeseries?bucket_seconds=300")
        assert resp.status_code == 200
        call_kwargs = mock_ts.call_args
        # bucket_seconds should be 300
        assert call_kwargs.kwargs.get("bucket_seconds") == 300 or \
               300 in (call_kwargs.args if call_kwargs.args else [])

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_with_limit(self, mock_ts):
        """Should accept custom limit parameter."""
        mock_ts.return_value = {"columns": [], "rows": [], "row_count": 0}
        resp = client.get("/api/v1/congestion/timeseries?limit=5000")
        assert resp.status_code == 200

    def test_timeseries_invalid_bucket(self):
        """bucket_seconds=0 should return 422 validation error."""
        resp = client.get("/api/v1/congestion/timeseries?bucket_seconds=0")
        assert resp.status_code == 422

    def test_timeseries_invalid_limit(self):
        """limit=0 should return 422 validation error."""
        resp = client.get("/api/v1/congestion/timeseries?limit=0")
        assert resp.status_code == 422

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_empty_result(self, mock_ts):
        """Empty result should return valid empty response."""
        mock_ts.return_value = {"columns": [], "rows": [], "row_count": 0}
        resp = client.get("/api/v1/congestion/timeseries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["row_count"] == 0
        assert data["rows"] == []

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_multi_space(self, mock_ts):
        """Should handle multiple spaces in result."""
        mock_ts.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 5],
                ["Room_B", "2026-03-19T10:00:00", 3],
                ["Room_A", "2026-03-19T10:01:00", 4],
                ["Room_B", "2026-03-19T10:01:00", 6],
            ],
            "row_count": 4,
        }
        resp = client.get("/api/v1/congestion/timeseries")
        assert resp.status_code == 200
        data = resp.json()
        assert data["row_count"] == 4
        # Verify both spaces present
        space_ids = {row[0] for row in data["rows"]}
        assert "Room_A" in space_ids
        assert "Room_B" in space_ids

    @patch("app.services.trino_service.query_space_congestion_timeseries")
    def test_timeseries_service_error(self, mock_ts):
        """Service exception should return 500."""
        mock_ts.side_effect = Exception("Trino connection refused")
        resp = client.get("/api/v1/congestion/timeseries")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════
#  Chart.js Configuration Verification
# ═══════════════════════════════════════════════════════════════════

class TestChartConfiguration:
    """Verify the Chart.js configuration in the dashboard HTML."""

    def _get_html(self):
        return client.get("/api/v1/dashboard/timeline").text

    def test_chart_type_is_line(self):
        """Chart type should be 'line' for time-series visualization."""
        html = self._get_html()
        assert "type: 'line'" in html

    def test_chart_uses_time_scale(self):
        """X-axis should use time scale type."""
        html = self._get_html()
        assert "type: 'time'" in html

    def test_chart_has_zoom_config(self):
        """Chart should configure zoom plugin."""
        html = self._get_html()
        assert "zoom:" in html
        assert "wheel:" in html
        assert "pan:" in html

    def test_chart_has_tooltip(self):
        """Chart should configure tooltips."""
        html = self._get_html()
        assert "tooltip:" in html or "tooltips:" in html

    def test_chart_y_axis_begins_at_zero(self):
        """Y-axis should begin at zero for congestion counts."""
        html = self._get_html()
        assert "beginAtZero: true" in html

    def test_chart_has_responsive(self):
        """Chart should be responsive."""
        html = self._get_html()
        assert "responsive: true" in html

    def test_chart_has_interaction_mode(self):
        """Chart should have index interaction mode for better tooltips."""
        html = self._get_html()
        assert "mode: 'index'" in html

    def test_hammerjs_included(self):
        """Hammer.js should be included for touch/pinch zoom support."""
        html = self._get_html()
        assert "hammerjs" in html.lower() or "hammer.min.js" in html
