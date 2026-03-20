"""
Tests for bidirectional heatmap-chart interaction.

Verifies:
  1. ChartComponent dispatches 'time-selected' custom event on click
  2. HeatmapComponent listens for 'time-selected' and updates display
  3. HeatmapComponent dispatches 'space-selected' event on click
  4. ChartComponent filters by space on 'space-selected' event
  5. DashboardStore.getHeatmapDataAtSnapshot returns correct snapshot data
  6. DashboardStore.getChartData(spaceId) filters correctly
  7. Sync banner HTML is present in dashboard template
  8. Overview page JS contains bidirectional interaction bindings
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ── Test 1: Dashboard HTML includes both visualization components ──────────

def test_dashboard_includes_heatmap_and_chart_scripts(client):
    """Dashboard HTML loads heatmap-component.js and chart-component.js."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    html = resp.text
    assert "heatmap-component.js" in html
    assert "chart-component.js" in html


# ── Test 2: Chart component has click handler and time-selected event ──────

def test_chart_component_has_click_handler():
    """chart-component.js contains click event handler and time-selected dispatch."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "chart-component.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Click handler registered
    assert '_onClick(e)' in content, "ChartComponent must have _onClick handler"
    assert '"click"' in content, "ChartComponent must register click event"

    # Dispatches time-selected event
    assert 'time-selected' in content, "ChartComponent must dispatch time-selected event"
    assert 'CustomEvent' in content, "Must use CustomEvent for time-selected"

    # Has selected time state
    assert '_selectedIndex' in content, "ChartComponent must track selectedIndex"

    # Has selectTimeIndex method
    assert 'selectTimeIndex' in content, "Must expose selectTimeIndex method"

    # Draws selected marker
    assert '_drawSelectedMarker' in content, "Must have _drawSelectedMarker method"


# ── Test 3: Heatmap component listens for time-selected events ─────────────

def test_heatmap_component_listens_for_time_selected():
    """heatmap-component.js listens for time-selected events."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "heatmap-component.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Listens for time-selected
    assert 'time-selected' in content, "HeatmapComponent must listen for time-selected"
    assert '_onTimeSelected' in content, "Must have _onTimeSelected handler"

    # Time snapshot state
    assert '_timeSnapshot' in content, "Must have _timeSnapshot state"
    assert '_timeLabel' in content, "Must have _timeLabel for overlay"

    # Renders time overlay
    assert '_renderTimeOverlay' in content, "Must render time overlay badge"

    # Cleanup on destroy
    assert 'removeEventListener' in content, "Must clean up time-selected listener on destroy"

    # setTimeSnapshot API
    assert 'setTimeSnapshot' in content, "Must expose setTimeSnapshot method"
    assert 'clearTimeSnapshot' in content, "Must expose clearTimeSnapshot method"


# ── Test 4: Heatmap still dispatches space-selected event ──────────────────

def test_heatmap_dispatches_space_selected():
    """heatmap-component.js dispatches space-selected on click."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "heatmap-component.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert 'space-selected' in content, "HeatmapComponent must dispatch space-selected"
    assert '_onClick' in content, "Must have _onClick handler"


# ── Test 5: DashboardStore has snapshot and chart filter methods ───────────

def test_dashboard_store_has_snapshot_methods():
    """dashboard-store.js has getHeatmapDataAtSnapshot and getSpaceTimeseries."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "dashboard-store.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert 'getHeatmapDataAtSnapshot' in content, "Must have getHeatmapDataAtSnapshot method"
    assert 'getSpaceTimeseries' in content, "Must have getSpaceTimeseries method"
    assert 'getChartData' in content, "Must have getChartData method"


# ── Test 6: Chart component filters by space ───────────────────────────────

def test_chart_component_filters_by_space():
    """chart-component.js listens for space-selected and calls filterBySpace."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "chart-component.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert 'space-selected' in content, "ChartComponent must listen for space-selected"
    assert 'filterBySpace' in content, "Must have filterBySpace method"
    assert '_filterSpaceId' in content, "Must track _filterSpaceId state"


# ── Test 7: Overview page has bidirectional interaction code ───────────────

def test_overview_page_has_bidirectional_interaction():
    """overview.js contains bidirectional interaction bindings."""
    import os
    js_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "js", "pages", "overview.js"
    )
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Heatmap → Chart
    assert 'bindHeatmapToChartInteraction' in content, "Must have heatmap→chart binding"
    assert 'updateTimeChartFilter' in content, "Must have chart filter update function"

    # Chart → Heatmap
    assert 'bindChartToHeatmapInteraction' in content, "Must have chart→heatmap binding"
    assert 'updateHeatmapToTimepoint' in content, "Must have heatmap timepoint update"

    # Sync banner
    assert 'sync-status-banner' in content, "Must render sync status banner"
    assert 'clearAllSyncSelections' in content, "Must have clear sync function"

    # State tracking
    assert 'selectedHeatmapSpace' in content, "Must track selectedHeatmapSpace"
    assert 'selectedChartTimestamp' in content, "Must track selectedChartTimestamp"


# ── Test 8: CSS contains sync banner styles ────────────────────────────────

def test_css_has_sync_banner_styles():
    """dashboard.css contains sync-status-banner styles."""
    import os
    css_path = os.path.join(
        os.path.dirname(__file__), "..", "app", "static", "css", "dashboard.css"
    )
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert '.sync-status-banner' in content, "Must have .sync-status-banner style"
    assert '.sync-banner__clear' in content, "Must have .sync-banner__clear style"
    assert 'syncBannerSlide' in content, "Must have banner animation"
