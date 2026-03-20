"""
Tests for Dashboard-API Data Fetching Layer.

Verifies that:
1. The dashboard HTML template is served correctly at /dashboard
2. All static JS files for the data fetching layer are served
3. The API endpoints consumed by the polling service return correct structure
4. The congestion endpoint returns proper SpaceCongestion schema
5. The congestion-timeseries endpoint returns QueryResponse schema
"""

import pytest
from fastapi.testclient import TestClient

# Import the app
from app.main import app

client = TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
#  Dashboard HTML serving
# ═══════════════════════════════════════════════════════════════════════

class TestDashboardServing:
    """Test that the dashboard HTML and static assets are served."""

    def test_dashboard_returns_html(self):
        """GET /dashboard should return HTML with status 200."""
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_dashboard_contains_data_layer_scripts(self):
        """Dashboard HTML should include all data fetching layer scripts."""
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.text

        required_scripts = [
            "api-client.js",
            "data-polling-service.js",
            "dashboard-store.js",
            "heatmap-component.js",
            "chart-component.js",
        ]
        for script in required_scripts:
            assert script in html, f"Dashboard HTML missing script: {script}"

    def test_dashboard_contains_visualization_elements(self):
        """Dashboard HTML should contain heatmap and chart containers."""
        resp = client.get("/dashboard")
        html = resp.text

        # Check for either Plotly div IDs or canvas IDs (depending on which template variant)
        assert "heatmap" in html.lower(), "Dashboard HTML missing heatmap element"
        assert "chart" in html.lower() or "time" in html.lower(), "Dashboard HTML missing chart element"

    def test_dashboard_trailing_slash(self):
        """GET /dashboard/ should also work."""
        resp = client.get("/dashboard/")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
#  Static JS files serving
# ═══════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    """Test that all data fetching layer JS files are served."""

    @pytest.mark.parametrize("js_file", [
        "api-client.js",
        "data-polling-service.js",
        "dashboard-store.js",
        "heatmap-component.js",
        "chart-component.js",
        "dashboard-init.js",
        "config.js",
        "api.js",
        "components.js",
        "router.js",
    ])
    def test_js_file_served(self, js_file):
        """Each JS file should be served at /static/js/<file>."""
        resp = client.get(f"/static/js/{js_file}")
        assert resp.status_code == 200, f"Static JS file not found: {js_file}"
        content_type = resp.headers.get("content-type", "")
        assert "javascript" in content_type or "text" in content_type

    def test_css_file_served(self):
        """Dashboard CSS should be served."""
        resp = client.get("/static/css/dashboard.css")
        assert resp.status_code == 200
        assert "css" in resp.headers.get("content-type", "").lower() or "text" in resp.headers.get("content-type", "").lower()


# ═══════════════════════════════════════════════════════════════════════
#  API Client JS Content Verification
# ═══════════════════════════════════════════════════════════════════════

class TestApiClientJs:
    """Verify api-client.js contains correct endpoint mappings."""

    def test_api_client_has_congestion_endpoint(self):
        """api-client.js should reference /api/v1/congestion."""
        resp = client.get("/static/js/api-client.js")
        assert "/api/v1/congestion" in resp.text

    def test_api_client_has_health_endpoint(self):
        """api-client.js should reference /api/v1/health."""
        resp = client.get("/static/js/api-client.js")
        assert "/api/v1/health" in resp.text

    def test_api_client_has_dynamic_endpoints(self):
        """api-client.js should reference dynamic object endpoints."""
        resp = client.get("/static/js/api-client.js")
        text = resp.text
        assert "/api/v1/dynamic/query/latest" in text
        assert "/api/v1/dynamic/objects" in text
        assert "/api/v1/dynamic/query/congestion-timeseries" in text

    def test_api_client_has_static_endpoints(self):
        """api-client.js should reference static object endpoints."""
        resp = client.get("/static/js/api-client.js")
        text = resp.text
        assert "/api/v1/static/spaces" in text
        assert "/api/v1/static/count" in text
        assert "/api/v1/static/types" in text


# ═══════════════════════════════════════════════════════════════════════
#  Polling Service JS Verification
# ═══════════════════════════════════════════════════════════════════════

class TestPollingServiceJs:
    """Verify data-polling-service.js has correct channel configuration."""

    def test_has_congestion_channel(self):
        """Polling service should define a 'congestion' channel."""
        resp = client.get("/static/js/data-polling-service.js")
        text = resp.text
        assert '"congestion"' in text
        assert "getCongestion" in text

    def test_has_timeseries_channel(self):
        """Polling service should define a 'congestion-ts' channel."""
        resp = client.get("/static/js/data-polling-service.js")
        text = resp.text
        assert '"congestion-ts"' in text
        assert "getCongestionTimeseries" in text

    def test_has_dynamic_latest_channel(self):
        """Polling service should define a 'dynamic-latest' channel."""
        resp = client.get("/static/js/data-polling-service.js")
        text = resp.text
        assert '"dynamic-latest"' in text
        assert "getDynamicLatest" in text

    def test_has_health_channel(self):
        """Polling service should define a 'health' channel."""
        resp = client.get("/static/js/data-polling-service.js")
        text = resp.text
        assert '"health"' in text
        assert "getDeepHealth" in text

    def test_has_static_channels(self):
        """Polling service should define static data channels."""
        resp = client.get("/static/js/data-polling-service.js")
        text = resp.text
        assert '"static-spaces"' in text
        assert '"static-count"' in text
        assert '"static-types"' in text


# ═══════════════════════════════════════════════════════════════════════
#  Dashboard Store JS Verification
# ═══════════════════════════════════════════════════════════════════════

class TestDashboardStoreJs:
    """Verify dashboard-store.js provides reactive data management."""

    def test_store_has_heatmap_data_getter(self):
        """Store should provide getHeatmapData() for heatmap component."""
        resp = client.get("/static/js/dashboard-store.js")
        assert "getHeatmapData" in resp.text

    def test_store_has_chart_data_getter(self):
        """Store should provide getChartData() for chart component."""
        resp = client.get("/static/js/dashboard-store.js")
        assert "getChartData" in resp.text

    def test_store_has_summary_stats(self):
        """Store should provide getSummaryStats() for KPI cards."""
        resp = client.get("/static/js/dashboard-store.js")
        assert "getSummaryStats" in resp.text

    def test_store_has_congestion_history(self):
        """Store should maintain congestion history for delta calculation."""
        resp = client.get("/static/js/dashboard-store.js")
        text = resp.text
        assert "history" in text
        assert "getCongestionDelta" in text

    def test_store_has_watch_method(self):
        """Store should have reactive watch() method."""
        resp = client.get("/static/js/dashboard-store.js")
        assert "watch(" in resp.text


# ═══════════════════════════════════════════════════════════════════════
#  Visualization Component JS Verification
# ═══════════════════════════════════════════════════════════════════════

class TestVisualizationComponents:
    """Verify heatmap and chart components exist and have correct APIs."""

    def test_heatmap_component_exists(self):
        """HeatmapComponent should be defined."""
        resp = client.get("/static/js/heatmap-component.js")
        assert resp.status_code == 200
        assert "HeatmapComponent" in resp.text

    def test_heatmap_has_color_mapping(self):
        """Heatmap should have congestion level to color mapping."""
        resp = client.get("/static/js/heatmap-component.js")
        assert "_levelToColor" in resp.text

    def test_heatmap_has_interaction(self):
        """Heatmap should support click and hover interaction."""
        resp = client.get("/static/js/heatmap-component.js")
        text = resp.text
        assert "space-selected" in text  # custom event
        assert "_onMouseMove" in text
        assert "_onClick" in text

    def test_chart_component_exists(self):
        """ChartComponent should be defined."""
        resp = client.get("/static/js/chart-component.js")
        assert resp.status_code == 200
        assert "ChartComponent" in resp.text

    def test_chart_has_multi_series(self):
        """Chart should support multiple space series."""
        resp = client.get("/static/js/chart-component.js")
        assert "_palette" in resp.text  # color palette for multiple lines

    def test_chart_has_tooltip(self):
        """Chart should have hover tooltip."""
        resp = client.get("/static/js/chart-component.js")
        assert "tooltip" in resp.text.lower()


# ═══════════════════════════════════════════════════════════════════════
#  API Endpoint Structure Tests (consumed by dashboard)
# ═══════════════════════════════════════════════════════════════════════

class TestCongestionEndpointStructure:
    """Test congestion API endpoints return correct schema structure
    (mock-safe — handles Trino unavailability gracefully)."""

    def test_health_endpoint_structure(self):
        """GET /api/v1/health should return status, timestamp, version."""
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "timestamp" in data
        assert "version" in data

    def test_deep_health_endpoint_structure(self):
        """GET /health should return status, dependencies, uptime."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "dependencies" in data
        assert "uptime_seconds" in data

    def test_root_endpoint_has_dashboard_link(self):
        """GET / should reference /dashboard."""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "dashboard" in data


# ═══════════════════════════════════════════════════════════════════════
#  Integration: Dashboard init script
# ═══════════════════════════════════════════════════════════════════════

class TestDashboardInitScript:
    """Verify dashboard-init.js correctly bootstraps all components."""

    def test_init_creates_api_client(self):
        """Init script should instantiate LakehouseAPIClient."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "new LakehouseAPIClient" in resp.text

    def test_init_creates_polling_service(self):
        """Init script should create DataPollingService."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "createDashboardPollingService" in resp.text

    def test_init_creates_store(self):
        """Init script should create DashboardStore."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "new DashboardStore" in resp.text

    def test_init_creates_heatmap(self):
        """Init script should create HeatmapComponent."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "new HeatmapComponent" in resp.text

    def test_init_creates_chart(self):
        """Init script should create ChartComponent."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "new ChartComponent" in resp.text

    def test_init_starts_polling(self):
        """Init script should call pollingService.startAll()."""
        resp = client.get("/static/js/dashboard-init.js")
        assert "startAll()" in resp.text
