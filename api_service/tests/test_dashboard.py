"""Tests for the web dashboard layout and routing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


class TestDashboardPage:
    """Test GET /dashboard serves the SPA HTML."""

    def test_dashboard_returns_html(self, client: TestClient):
        """Dashboard endpoint should return HTML 200."""
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_trailing_slash(self, client: TestClient):
        """Dashboard with trailing slash should also work."""
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_app_shell(self, client: TestClient):
        """HTML should contain the app shell structure."""
        resp = client.get("/dashboard")
        html = resp.text
        assert "app-shell" in html
        assert "navbar" in html
        assert "page-content" in html

    def test_dashboard_contains_plotly_script(self, client: TestClient):
        """HTML should include Plotly.js for charting."""
        resp = client.get("/dashboard")
        html = resp.text
        assert "plotly" in html.lower()

    def test_dashboard_contains_nav_routes(self, client: TestClient):
        """HTML should contain hash-based navigation links."""
        resp = client.get("/dashboard")
        html = resp.text
        assert "#/overview" in html
        assert "#/spaces" in html
        assert "#/query" in html

    def test_dashboard_loads_js_modules(self, client: TestClient):
        """HTML should reference all required JS modules."""
        resp = client.get("/dashboard")
        html = resp.text
        for js_file in ["config.js", "api.js", "components.js", "router.js",
                        "pages/overview.js", "pages/spaces.js", "pages/query.js"]:
            assert js_file in html, f"Missing JS reference: {js_file}"

    def test_dashboard_loads_css(self, client: TestClient):
        """HTML should reference the dashboard stylesheet."""
        resp = client.get("/dashboard")
        assert "dashboard.css" in resp.text


class TestStaticAssets:
    """Test that static CSS/JS files are served correctly."""

    def test_css_served(self, client: TestClient):
        """Dashboard CSS should be accessible."""
        resp = client.get("/static/css/dashboard.css")
        assert resp.status_code == 200
        assert "text/css" in resp.headers["content-type"]
        assert "app-shell" in resp.text

    def test_js_config_served(self, client: TestClient):
        resp = client.get("/static/js/config.js")
        assert resp.status_code == 200
        assert "DashboardConfig" in resp.text

    def test_js_api_served(self, client: TestClient):
        resp = client.get("/static/js/api.js")
        assert resp.status_code == 200
        assert "LakehouseAPI" in resp.text

    def test_js_router_served(self, client: TestClient):
        resp = client.get("/static/js/router.js")
        assert resp.status_code == 200
        assert "Router" in resp.text

    def test_js_components_served(self, client: TestClient):
        resp = client.get("/static/js/components.js")
        assert resp.status_code == 200
        assert "Components" in resp.text

    def test_js_overview_page_served(self, client: TestClient):
        resp = client.get("/static/js/pages/overview.js")
        assert resp.status_code == 200
        assert "OverviewPage" in resp.text
        assert "heatmap" in resp.text.lower()

    def test_js_spaces_page_served(self, client: TestClient):
        resp = client.get("/static/js/pages/spaces.js")
        assert resp.status_code == 200
        assert "SpacesPage" in resp.text

    def test_js_query_page_served(self, client: TestClient):
        resp = client.get("/static/js/pages/query.js")
        assert resp.status_code == 200
        assert "QueryPage" in resp.text


class TestRootEndpoint:
    """Test root endpoint includes dashboard link."""

    def test_root_includes_dashboard_link(self, client: TestClient):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "dashboard" in data
        assert data["dashboard"] == "/dashboard"
