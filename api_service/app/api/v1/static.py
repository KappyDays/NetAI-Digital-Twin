"""
Static object endpoints.

Static objects = Stage Prims stored at space-level granularity.
Space = each direct child of /World in the USD stage.

Query endpoints use Trino SQL on the Iceberg static table.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import logger
from app.models.schemas import (
    PrimInsertRequest,
    PrimInsertResponse,
    QueryResponse,
    SpaceDrilldownResponse,
    SpaceOverwriteRequest,
    SpaceOverwriteResponse,
    StaticCountResponse,
    StaticSpaceInfo,
    StaticSpacesResponse,
    StaticTableInfoResponse,
    StaticTypeSummaryItem,
    StaticTypeSummaryResponse,
)
from app.services import iceberg_service, trino_service

router = APIRouter(prefix="/static", tags=["Static Objects"])


# ─────────────────────────────────────────────────────────────────────
#  Write Endpoints
# ─────────────────────────────────────────────────────────────────────

@router.post("/prims", response_model=PrimInsertResponse)
async def insert_prims(request: PrimInsertRequest):
    """
    Batch insert static Prim records into the Iceberg table.

    Called by the Isaac Sim lakehouse.proto extension (Task 1).
    Each record contains prim_path, type, and properties JSON.
    The space_id is auto-derived from /World/<SpaceName>/... path pattern.
    """
    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    try:
        records = [r.model_dump() for r in request.records]
        count = iceberg_service.insert_static_prims(records)
        table_name = (
            f"{iceberg_service.settings.iceberg_namespace}"
            f".{iceberg_service.settings.iceberg_table_name}"
        )
        return PrimInsertResponse(
            inserted=count,
            table=table_name,
            message=f"Successfully inserted {count} static prim records",
        )
    except Exception as e:
        logger.error("Failed to insert static prims: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
#  Read / Query Endpoints
# ─────────────────────────────────────────────────────────────────────

@router.get("/prims", response_model=QueryResponse)
async def get_prims(
    space_id: Optional[str] = Query(None, description="Filter by space_id"),
    prim_type: Optional[str] = Query(None, description="Filter by Prim type (e.g. Mesh, Xform)"),
    limit: int = Query(10000, ge=1, le=100000, description="Max rows"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
):
    """
    Query static Prim records with optional filters.

    - No filters: returns all prims (paginated).
    - space_id: returns prims belonging to that space.
    - prim_type: returns prims of that USD type.
    - Both: combined AND filter.
    """
    try:
        if space_id:
            result = trino_service.query_static_by_space(
                space_id=space_id, prim_type=prim_type, limit=limit, offset=offset,
            )
        elif prim_type:
            result = trino_service.query_static_by_type(
                prim_type=prim_type, limit=limit, offset=offset,
            )
        else:
            result = trino_service.query_static_all(limit=limit, offset=offset)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Static prims query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prims/path", response_model=QueryResponse)
async def get_prims_by_path(
    prim_path: str = Query(..., description="USD Prim path to search"),
    exact: bool = Query(True, description="True=exact match, False=prefix match (path%)"),
):
    """
    Query static Prim(s) by their USD path.

    - exact=True: returns the single prim with that exact path.
    - exact=False: prefix match — returns the prim and all descendants.
      e.g. /World/Room_A → /World/Room_A, /World/Room_A/Chair, etc.
    """
    try:
        result = trino_service.query_static_by_prim_path(
            prim_path=prim_path, exact=exact,
        )
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Static path query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prims/search", response_model=QueryResponse)
async def search_prims_by_properties(
    key: str = Query(..., description="JSON property key to search (e.g. 'material')"),
    value: Optional[str] = Query(None, description="Optional value to match"),
    space_id: Optional[str] = Query(None, description="Optional space filter"),
    limit: int = Query(10000, ge=1, le=100000),
):
    """
    Search static Prims by properties JSON content.

    Uses Trino json_extract_scalar to find prims whose properties
    contain the given key (and optionally match a value).
    """
    try:
        result = trino_service.query_static_properties_search(
            search_key=key, search_value=value,
            space_id=space_id, limit=limit,
        )
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Static properties search failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prims/hierarchy", response_model=QueryResponse)
async def get_prims_hierarchy(
    root_path: str = Query("/World", description="Root path for hierarchy query"),
    max_depth: Optional[int] = Query(None, ge=1, le=20, description="Max depth from root"),
):
    """
    Query static Prims as a hierarchy rooted at root_path.

    Returns prim records with a computed 'depth' column indicating
    their level in the scene graph relative to root_path.
    """
    try:
        result = trino_service.query_static_hierarchy(
            root_path=root_path, max_depth=max_depth,
        )
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Static hierarchy query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prims/latest", response_model=QueryResponse)
async def get_latest_ingestion():
    """
    Get the most recently ingested batch of static Prims.

    Returns all records that share the maximum ingested_at timestamp.
    Useful for verifying Isaac Sim → Lakehouse sync status.
    """
    try:
        result = trino_service.query_static_latest_ingestion()
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Static latest-ingestion query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spaces", response_model=StaticSpacesResponse)
async def list_spaces():
    """
    List all spaces (/World direct children) with aggregated metadata.

    Returns space_id, prim_count, distinct type count, and last ingestion
    timestamp for each space.
    """
    try:
        result = trino_service.list_static_spaces()
        spaces = []
        for row in result["rows"]:
            spaces.append(StaticSpaceInfo(
                space_id=row[0],
                prim_count=row[1],
                type_count=row[2],
                last_ingested=row[3] if len(row) > 3 else None,
            ))
        return StaticSpacesResponse(spaces=spaces, total_spaces=len(spaces))
    except Exception as e:
        logger.error("Static spaces listing failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/spaces/{space_id}/drilldown", response_model=SpaceDrilldownResponse)
async def get_space_drilldown(space_id: str):
    """
    Get full drill-down data for a specific space.

    Returns object-level detail including:
    - All static Prims with parsed position, rotation, scale, metadata
    - All dynamic objects with latest state, position, and activity status
    - Type distribution summary
    - Navigation context for space summary ↔ drill-down transitions

    Path Parameters:
        space_id: The space identifier (direct /World child name).
    """
    try:
        result = trino_service.query_space_drilldown(space_id)
        return SpaceDrilldownResponse(**result)
    except Exception as e:
        logger.error("Space drilldown failed for '%s': %s", space_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/count", response_model=StaticCountResponse)
async def get_static_count():
    """
    Get the total count of static Prim records and per-space breakdown.
    """
    try:
        result = trino_service.query_static_count()
        return StaticCountResponse(**result)
    except Exception as e:
        logger.error("Static count query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/types", response_model=StaticTypeSummaryResponse)
async def get_type_summary(
    space_id: Optional[str] = Query(None, description="Optional space filter"),
):
    """
    Get a breakdown of Prim types and their counts.

    Optionally filtered by space_id. Useful for understanding
    scene composition at a glance.
    """
    try:
        result = trino_service.query_static_type_summary(space_id=space_id)
        types = []
        for row in result["rows"]:
            types.append(StaticTypeSummaryItem(type=row[0], prim_count=row[1]))
        return StaticTypeSummaryResponse(types=types, total_types=len(types))
    except Exception as e:
        logger.error("Static type summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
#  Space-level Overwrite (full replace)
# ─────────────────────────────────────────────────────────────────────

@router.put("/spaces/{space_id}/prims", response_model=SpaceOverwriteResponse)
async def overwrite_space_prims(space_id: str, request: SpaceOverwriteRequest):
    """
    Replace ALL static Prim records for a specific space.

    Performs a full overwrite: deletes existing data for the space,
    then inserts the new records. Used when Isaac Sim re-exports all
    prims for a space after scene modifications.

    Path Parameters:
        space_id: The space identifier (direct /World child name).

    Body:
        records: List of PrimRecord dicts to insert for this space.
    """
    try:
        records = [r.model_dump() for r in request.records]
        count = iceberg_service.overwrite_space_prims(space_id, records)
        table_name = (
            f"{iceberg_service.settings.iceberg_namespace}"
            f".{iceberg_service.settings.iceberg_table_name}"
        )
        return SpaceOverwriteResponse(
            space_id=space_id,
            inserted=count,
            table=table_name,
            message=f"Overwrote space '{space_id}' with {count} prim records",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Space overwrite failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/spaces/{space_id}/prims")
async def delete_space_prims(space_id: str):
    """
    Delete ALL static Prim records for a specific space.

    Path Parameters:
        space_id: The space identifier to remove.
    """
    try:
        iceberg_service.delete_space_prims(space_id)
        return {"message": f"Deleted all prims for space '{space_id}'", "space_id": space_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Space deletion failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────
#  Table Info (Schema / Metadata)
# ─────────────────────────────────────────────────────────────────────

@router.get("/table-info", response_model=StaticTableInfoResponse)
async def get_static_table_info():
    """
    Return metadata about the static_prims Iceberg table.

    Includes schema definition, partition spec, snapshot count,
    and storage location. Useful for debugging and monitoring.
    """
    try:
        info = iceberg_service.get_static_table_info()
        return StaticTableInfoResponse(**info)
    except Exception as e:
        logger.error("Static table info failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
