"""
Web dashboard endpoints.

Serves the Lakehouse Digital-Twin dashboard as a single-page HTML application.
Uses Plotly.js for Top-View heatmap + time-series chart visualization.

Routes:
    GET /dashboard       — Main dashboard (SPA with heatmap + time charts)
    GET /dashboard/timeline — Legacy congestion timeline page
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Dashboard"])

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
@router.get("/dashboard/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_page():
    """
    Serve the Lakehouse Digital-Twin web dashboard.

    Single-page application with:
    - Top-View spatial congestion heatmap (Plotly.js)
    - Time-series congestion chart
    - KPI summary strip
    - Space browser
    - Ad-hoc SQL query interface
    - Hash-based client-side routing (#/overview, #/spaces, #/query)
    """
    html_path = _TEMPLATE_DIR / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@router.get("/dashboard/timeline", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_timeline_page():
    """
    Serve the legacy congestion timeline dashboard.

    Chart.js time-series line chart for congestion trends.
    Preserved for backward compatibility.
    """
    html_path = _TEMPLATE_DIR / "congestion_timeline.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    # Fall back to main dashboard if legacy template missing
    return await dashboard_page()
