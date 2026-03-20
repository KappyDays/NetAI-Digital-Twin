"""
Query and visualization endpoints.

Provides SQL query passthrough and congestion aggregation for
the Extension UI and web dashboard.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.core.logging import logger
from app.models.schemas import CongestionGridResponse, CongestionResponse, QueryRequest, QueryResponse
from app.services import trino_service

router = APIRouter(tags=["Query & Visualization"])


@router.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    Execute an ad-hoc SQL query via Trino on Iceberg tables.

    Use for custom data exploration and dashboard widgets.
    """
    if not request.sql.strip():
        raise HTTPException(status_code=400, detail="Empty SQL query")

    try:
        result = trino_service.execute_query(request.sql)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Trino query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/congestion", response_model=CongestionResponse)
async def get_congestion():
    """
    Get current space congestion data.

    Aggregates the latest position of each dynamic object,
    groups by space_id, and returns normalized congestion levels.
    Used by both Extension UI and web dashboard for heatmap visualization.
    """
    try:
        result = trino_service.get_space_congestion()
        return CongestionResponse(**result)
    except Exception as e:
        logger.error("Congestion query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/congestion/timeseries", response_model=QueryResponse)
async def get_congestion_timeseries(
    space_id: Optional[str] = Query(None, description="Filter by space_id (omit for all)"),
    start_time: Optional[datetime] = Query(None, description="Start of time window (ISO 8601)"),
    end_time: Optional[datetime] = Query(None, description="End of time window (ISO 8601)"),
    bucket_seconds: int = Query(60, ge=1, le=86400, description="Time bucket size in seconds"),
    limit: int = Query(1000, ge=1, le=50000, description="Max result rows"),
):
    """
    Get congestion time-series data for dashboard timeline charts.

    Returns (space_id, time_bucket, object_count) rows grouped by
    configurable time buckets. Supports optional space and time filters.
    Used by the web dashboard timeline chart component.
    """
    try:
        result = trino_service.query_space_congestion_timeseries(
            space_id=space_id,
            start_time=start_time,
            end_time=end_time,
            bucket_seconds=bucket_seconds,
            limit=limit,
        )
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Congestion timeseries GET failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/congestion/grid", response_model=CongestionGridResponse)
async def get_congestion_grid(
    x_min: float = Query(-50.0, description="World X-coordinate minimum bound"),
    x_max: float = Query(50.0, description="World X-coordinate maximum bound"),
    y_min: float = Query(-50.0, description="World Y-coordinate minimum bound"),
    y_max: float = Query(50.0, description="World Y-coordinate maximum bound"),
    rows: int = Query(20, ge=1, le=200, description="Number of grid rows"),
    cols: int = Query(20, ge=1, le=200, description="Number of grid columns"),
):
    """
    Get 2D grid-based congestion data for top-view heatmap visualization.

    Divides the world space into a rows×cols grid and maps each dynamic
    object's latest position into the corresponding cell. Returns both
    a sparse cell list (non-empty cells with object IDs) and a dense
    grid matrix for direct heatmap rendering.

    Query Parameters:
        x_min, x_max, y_min, y_max: World-space bounds for the grid.
        rows, cols: Grid resolution (default 20×20).

    Used by the web dashboard heatmap component (Canvas/D3.js).
    """
    if x_min >= x_max or y_min >= y_max:
        raise HTTPException(
            status_code=400,
            detail="Invalid bounds: x_min must be < x_max and y_min must be < y_max",
        )

    try:
        result = trino_service.get_congestion_grid(
            x_min=x_min, x_max=x_max,
            y_min=y_min, y_max=y_max,
            rows=rows, cols=cols,
        )
        return CongestionGridResponse(**result)
    except Exception as e:
        logger.error("Congestion grid query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
