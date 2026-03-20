"""
Dynamic object endpoints.

Dynamic objects = IoT / tracking entities with per-object Iceberg tables.
Each object gets its own table: dynamic_<object_id> with a fixed schema
designed for schema evolution compatibility.

Provides:
  - Ingestion endpoint (POST)
  - Time-range queries with pagination & filtering
  - Spatial filter queries (by space_id or bounding box) with pagination
  - Trajectory queries with pagination
  - Latest state queries
  - Congestion time-series queries
  - GET-based paginated queries for Extension UI / dashboard convenience
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import logger
from app.models.schemas import (
    CongestionTimeseriesRequest,
    DynamicInsertRequest,
    DynamicInsertResponse,
    DynamicObjectListResponse,
    DynamicSpaceQueryRequest,
    DynamicSpatialRangeRequest,
    DynamicTimeRangeRequest,
    DynamicTrajectoryRequest,
    PaginatedQueryResponse,
    QueryResponse,
)
from app.services import iceberg_service, trino_service

router = APIRouter(prefix="/dynamic", tags=["Dynamic Objects"])


# ═══════════════════════════════════════════════════════════════════════
#  Ingestion
# ═══════════════════════════════════════════════════════════════════════

@router.post("/ingest", response_model=DynamicInsertResponse)
async def ingest_dynamic_records(request: DynamicInsertRequest):
    """
    Ingest IoT / tracking data for a dynamic object.

    Automatically creates a per-object Iceberg table if it doesn't exist.
    The table name follows the pattern: dynamic_<object_id>.
    """
    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    object_id = request.records[0].object_id

    try:
        records = [r.model_dump() for r in request.records]
        count, table_name = iceberg_service.insert_dynamic_records(object_id, records)
        return DynamicInsertResponse(
            inserted=count,
            table=table_name,
            object_id=object_id,
            message=f"Inserted {count} records for object {object_id}",
        )
    except Exception as e:
        logger.error("Failed to ingest dynamic records: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Discovery
# ═══════════════════════════════════════════════════════════════════════

@router.get("/objects", response_model=DynamicObjectListResponse)
async def list_objects():
    """
    List all registered dynamic objects with metadata.

    Returns each object's ID, table name, record count, and time range.
    """
    try:
        objects = trino_service.list_dynamic_objects()
        return DynamicObjectListResponse(objects=objects, total=len(objects))
    except Exception as e:
        logger.error("Failed to list dynamic objects: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables", response_model=list[str])
async def list_tables():
    """List all dynamic_* table names in the Iceberg namespace."""
    try:
        return trino_service.list_dynamic_tables()
    except Exception as e:
        logger.error("Failed to list dynamic tables: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Time-Range Query (POST — full control with body parameters)
# ═══════════════════════════════════════════════════════════════════════

@router.post("/query/time-range", response_model=PaginatedQueryResponse)
async def query_by_time_range(request: DynamicTimeRangeRequest):
    """
    Query dynamic object records within a time window.

    Returns all columns for the specified object between start_time and end_time,
    ordered by timestamp. Supports offset-based pagination and optional filters
    for speed range and space_id.

    Pagination: Use `offset` and `limit` to page through large result sets.
    The response includes `has_more` to indicate if additional pages exist.
    """
    if request.start_time >= request.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    try:
        result = trino_service.query_dynamic_by_time_range(
            object_id=request.object_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset,
            order=request.order,
            speed_min=request.speed_min,
            speed_max=request.speed_max,
            space_id=request.space_id,
        )
        return PaginatedQueryResponse(**result)
    except Exception as e:
        logger.error("Time-range query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Time-Range Query (GET — convenience for Extension UI / dashboard)
# ═══════════════════════════════════════════════════════════════════════

@router.get("/query/time-range", response_model=PaginatedQueryResponse)
async def query_by_time_range_get(
    object_id: str = Query(..., description="Dynamic object identifier"),
    start_time: datetime = Query(..., description="Start of time window (ISO 8601)"),
    end_time: datetime = Query(..., description="End of time window (ISO 8601)"),
    limit: int = Query(1000, ge=1, le=100000, description="Max rows per page"),
    offset: int = Query(0, ge=0, description="Rows to skip for pagination"),
    order: str = Query("ASC", description="Sort order: ASC or DESC"),
    speed_min: Optional[float] = Query(None, ge=0.0, description="Min speed filter"),
    speed_max: Optional[float] = Query(None, ge=0.0, description="Max speed filter"),
    space_id: Optional[str] = Query(None, description="Space/zone filter"),
):
    """
    GET variant of time-range query for easy browser/Extension access.

    Provides identical functionality to POST /query/time-range but accepts
    all parameters as query strings. Ideal for Omniverse Extension UI
    (urllib-based) and dashboard widgets that need simple URL-based queries.

    Pagination: Increment `offset` by `limit` to fetch subsequent pages.
    Check `has_more` in the response to know if more data is available.
    """
    if start_time >= end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    try:
        result = trino_service.query_dynamic_by_time_range(
            object_id=object_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
            order=order,
            speed_min=speed_min,
            speed_max=speed_max,
            space_id=space_id,
        )
        return PaginatedQueryResponse(**result)
    except Exception as e:
        logger.error("Time-range GET query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Space (Zone) Filter Query
# ═══════════════════════════════════════════════════════════════════════

@router.post("/query/by-space", response_model=PaginatedQueryResponse)
async def query_by_space(request: DynamicSpaceQueryRequest):
    """
    Query all dynamic objects in a given space/zone.

    Searches across ALL dynamic tables for records matching the space_id.
    Optionally filters by time range and object_type.
    Supports offset-based pagination.
    """
    try:
        result = trino_service.query_dynamic_by_space(
            space_id=request.space_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset,
            object_type=request.object_type,
        )
        return PaginatedQueryResponse(**result)
    except Exception as e:
        logger.error("Space query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Latest State
# ═══════════════════════════════════════════════════════════════════════

@router.get("/query/latest", response_model=QueryResponse)
async def query_latest(
    object_id: Optional[str] = Query(None, description="Object ID (omit for all objects)"),
):
    """
    Get the latest record for a specific or all dynamic objects.

    If object_id is provided, returns the most recent record for that object.
    Otherwise, returns the latest record for every registered dynamic object.
    """
    try:
        result = trino_service.query_dynamic_latest(object_id=object_id)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Latest query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Trajectory Query
# ═══════════════════════════════════════════════════════════════════════

@router.post("/query/trajectory", response_model=PaginatedQueryResponse)
async def query_trajectory(request: DynamicTrajectoryRequest):
    """
    Query the movement trajectory of a dynamic object.

    Returns time-ordered position data for visualization. Supports optional
    downsampling by averaging positions into N-second time buckets.
    Supports offset-based pagination for long trajectories.
    """
    if request.start_time >= request.end_time:
        raise HTTPException(status_code=400, detail="start_time must be before end_time")

    try:
        result = trino_service.query_dynamic_trajectory(
            object_id=request.object_id,
            start_time=request.start_time,
            end_time=request.end_time,
            sample_interval_seconds=request.sample_interval_seconds,
            limit=request.limit,
            offset=request.offset,
        )
        return PaginatedQueryResponse(**result)
    except Exception as e:
        logger.error("Trajectory query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Spatial Bounding Box Query
# ═══════════════════════════════════════════════════════════════════════

@router.post("/query/spatial-range", response_model=PaginatedQueryResponse)
async def query_spatial_range(request: DynamicSpatialRangeRequest):
    """
    Query dynamic objects within a spatial bounding box.

    Filters by coordinate range (pos_x, pos_y, optionally pos_z) across
    ALL dynamic tables. Optionally filters by time range.
    Supports offset-based pagination.
    """
    if request.x_min > request.x_max:
        raise HTTPException(status_code=400, detail="x_min must be <= x_max")
    if request.y_min > request.y_max:
        raise HTTPException(status_code=400, detail="y_min must be <= y_max")
    if request.z_min is not None and request.z_max is not None and request.z_min > request.z_max:
        raise HTTPException(status_code=400, detail="z_min must be <= z_max")

    try:
        result = trino_service.query_dynamic_spatial_range(
            x_min=request.x_min, x_max=request.x_max,
            y_min=request.y_min, y_max=request.y_max,
            z_min=request.z_min, z_max=request.z_max,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset,
        )
        return PaginatedQueryResponse(**result)
    except Exception as e:
        logger.error("Spatial range query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Congestion Time-Series
# ═══════════════════════════════════════════════════════════════════════

@router.post("/query/congestion-timeseries", response_model=QueryResponse)
async def query_congestion_timeseries(request: CongestionTimeseriesRequest):
    """
    Compute congestion (distinct object count) per time bucket per space.

    Groups dynamic object records into time buckets and counts distinct
    objects per space_id. Used for time-series congestion charts on the
    web dashboard and Extension UI.
    """
    try:
        result = trino_service.query_space_congestion_timeseries(
            space_id=request.space_id,
            start_time=request.start_time,
            end_time=request.end_time,
            bucket_seconds=request.bucket_seconds,
            limit=request.limit,
        )
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Congestion timeseries query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
