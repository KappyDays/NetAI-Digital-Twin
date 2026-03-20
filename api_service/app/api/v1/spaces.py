"""
Spaces endpoints — congestion summary and per-space object detail.

Provides a unified view combining Static (USD Prim) and Dynamic (IoT) data
per space for congestion visualization on Extension UI and web dashboard.

Space = each direct child Prim of /World in the USD stage.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.logging import logger
from app.models.schemas import (
    CongestionResponse,
    SpaceCongestion,
)
from app.services import trino_service

router = APIRouter(prefix="/spaces", tags=["Spaces & Congestion"])


# ═══════════════════════════════════════════════════════════════════════
#  Response Models (local to this router to avoid bloating schemas.py)
# ═══════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class StaticObjectSummary(BaseModel):
    """Static Prim object summary within a space."""
    prim_path: str
    object_type: str
    properties: Optional[str] = "{}"


class DynamicObjectSummary(BaseModel):
    """Dynamic object latest state within a space."""
    object_id: str
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    speed: float = 0.0
    timestamp: Optional[str] = None
    properties: Optional[str] = "{}"


class SpaceObjectsResponse(BaseModel):
    """Combined static + dynamic objects for a single space."""
    space_id: str
    static_objects: list[StaticObjectSummary] = Field(default_factory=list)
    dynamic_objects: list[DynamicObjectSummary] = Field(default_factory=list)
    static_count: int = 0
    dynamic_count: int = 0
    total_count: int = 0


class SpaceCongestionDetail(BaseModel):
    """Extended congestion data for a single space."""
    space_id: str
    static_prim_count: int = 0
    dynamic_object_count: int = 0
    total_object_count: int = 0
    congestion_level: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Normalized congestion 0.0 (empty) — 1.0 (full)",
    )
    type_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Static Prim type breakdown (e.g. {'Mesh': 10, 'Xform': 5})",
    )


class CongestionSummaryResponse(BaseModel):
    """Aggregated congestion summary across all spaces."""
    spaces: list[SpaceCongestionDetail] = Field(default_factory=list)
    total_spaces: int = 0
    total_static_prims: int = 0
    total_dynamic_objects: int = 0
    snapshot_time: str


# ═══════════════════════════════════════════════════════════════════════
#  GET /spaces/congestion/summary
# ═══════════════════════════════════════════════════════════════════════

@router.get(
    "/congestion/summary",
    response_model=CongestionSummaryResponse,
    summary="Space-level congestion summary",
)
async def get_congestion_summary():
    """
    Return an aggregated congestion summary for every space.

    Combines:
    - **Static data**: per-space Prim counts and type distribution from the
      Iceberg static_prims table.
    - **Dynamic data**: count of dynamic objects whose latest position is in
      each space (derived from per-object dynamic_* tables).

    The ``congestion_level`` is normalized as:
        dynamic_object_count / max(total_dynamic_objects, 1)
    (linear normalization — can be refined with per-space capacity metadata).

    Used by:
    - Isaac Sim Extension UI heatmap overlay
    - Web dashboard congestion chart
    """
    try:
        now = datetime.now(timezone.utc)

        # ── Gather static space data ──────────────────────────────
        static_spaces: dict[str, dict] = {}
        try:
            space_result = trino_service.list_static_spaces()
            for row in space_result.get("rows", []):
                sid = row[0]
                static_spaces[sid] = {
                    "prim_count": row[1] if len(row) > 1 else 0,
                    "type_count": row[2] if len(row) > 2 else 0,
                }
        except Exception as e:
            logger.warning("Static space query failed (table may not exist): %s", e)

        # ── Gather static type distribution per space ─────────────
        type_distributions: dict[str, dict[str, int]] = {}
        for sid in static_spaces:
            try:
                type_result = trino_service.query_static_type_summary(space_id=sid)
                dist = {}
                for row in type_result.get("rows", []):
                    dist[row[0]] = row[1]
                type_distributions[sid] = dist
            except Exception as e:
                logger.warning("Type summary for space %s failed: %s", sid, e)
                type_distributions[sid] = {}

        # ── Gather dynamic congestion data ────────────────────────
        dynamic_spaces: dict[str, int] = {}
        total_dynamic = 0
        try:
            congestion_result = trino_service.get_space_congestion()
            for sp in congestion_result.get("spaces", []):
                sid = sp["space_id"]
                cnt = sp["object_count"]
                dynamic_spaces[sid] = cnt
            total_dynamic = congestion_result.get("total_objects", 0)
        except Exception as e:
            logger.warning("Dynamic congestion query failed (no dynamic tables?): %s", e)

        # ── Merge into unified summary ────────────────────────────
        all_space_ids = sorted(
            set(static_spaces.keys()) | set(dynamic_spaces.keys())
        )
        total_static = sum(s["prim_count"] for s in static_spaces.values())

        spaces = []
        for sid in all_space_ids:
            static_count = static_spaces.get(sid, {}).get("prim_count", 0)
            dynamic_count = dynamic_spaces.get(sid, 0)
            congestion = min(dynamic_count / max(total_dynamic, 1), 1.0)

            spaces.append(SpaceCongestionDetail(
                space_id=sid,
                static_prim_count=static_count,
                dynamic_object_count=dynamic_count,
                total_object_count=static_count + dynamic_count,
                congestion_level=round(congestion, 4),
                type_distribution=type_distributions.get(sid, {}),
            ))

        return CongestionSummaryResponse(
            spaces=spaces,
            total_spaces=len(spaces),
            total_static_prims=total_static,
            total_dynamic_objects=total_dynamic,
            snapshot_time=now.isoformat(),
        )

    except Exception as e:
        logger.error("Congestion summary failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
#  GET /spaces/{space_id}/objects
# ═══════════════════════════════════════════════════════════════════════

@router.get(
    "/{space_id}/objects",
    response_model=SpaceObjectsResponse,
    summary="Per-space object detail (static + dynamic)",
)
async def get_space_objects(
    space_id: str,
    include_static: bool = Query(True, description="Include static Prim objects"),
    include_dynamic: bool = Query(True, description="Include dynamic IoT objects"),
    static_limit: int = Query(10000, ge=1, le=100000, description="Max static objects"),
    dynamic_limit: int = Query(10000, ge=1, le=100000, description="Max dynamic objects"),
):
    """
    Return all objects (static Prims + dynamic IoT entities) in a specific space.

    **Static objects**: USD Prims stored in the Iceberg ``static_prims`` table
    whose ``space_id`` matches. Returns prim_path, type, and properties.

    **Dynamic objects**: Latest position/state for each dynamic entity whose
    most recent ``space_id`` matches. Derived from per-object ``dynamic_*``
    Iceberg tables.

    Query parameters allow filtering to static-only or dynamic-only, and
    controlling pagination limits independently.

    Used by:
    - Extension UI: scene graph overlay and real-time object listing
    - Web dashboard: per-space drill-down view
    """
    try:
        static_objects: list[StaticObjectSummary] = []
        dynamic_objects: list[DynamicObjectSummary] = []

        # ── Static objects ────────────────────────────────────────
        if include_static:
            try:
                result = trino_service.query_static_by_space(
                    space_id=space_id, limit=static_limit,
                )
                columns = result.get("columns", [])
                col_map = {c: i for i, c in enumerate(columns)}
                for row in result.get("rows", []):
                    static_objects.append(StaticObjectSummary(
                        prim_path=row[col_map.get("prim_path", 0)],
                        object_type=row[col_map.get("type", 1)],
                        properties=row[col_map.get("properties", 2)] if "properties" in col_map else "{}",
                    ))
            except Exception as e:
                logger.warning(
                    "Static objects query for space %s failed: %s", space_id, e,
                )

        # ── Dynamic objects (latest per object in this space) ─────
        if include_dynamic:
            try:
                result = trino_service.query_dynamic_by_space(
                    space_id=space_id, limit=dynamic_limit,
                )
                columns = result.get("columns", [])
                col_map = {c: i for i, c in enumerate(columns)}

                # Deduplicate to latest record per object_id
                latest_by_obj: dict[str, dict] = {}
                for row in result.get("rows", []):
                    oid = row[col_map.get("object_id", 0)]
                    ts = row[col_map.get("timestamp", 1)]
                    if oid not in latest_by_obj or str(ts) > str(latest_by_obj[oid]["timestamp"]):
                        latest_by_obj[oid] = {
                            "object_id": oid,
                            "pos_x": row[col_map.get("pos_x", 2)] or 0.0,
                            "pos_y": row[col_map.get("pos_y", 3)] or 0.0,
                            "pos_z": row[col_map.get("pos_z", 4)] or 0.0,
                            "speed": row[col_map.get("speed", 8)] or 0.0,
                            "timestamp": str(ts) if ts else None,
                            "properties": row[col_map.get("properties", 10)] if "properties" in col_map else "{}",
                        }

                dynamic_objects = [
                    DynamicObjectSummary(**v) for v in latest_by_obj.values()
                ]
            except Exception as e:
                logger.warning(
                    "Dynamic objects query for space %s failed: %s", space_id, e,
                )

        s_count = len(static_objects)
        d_count = len(dynamic_objects)

        return SpaceObjectsResponse(
            space_id=space_id,
            static_objects=static_objects,
            dynamic_objects=dynamic_objects,
            static_count=s_count,
            dynamic_count=d_count,
            total_count=s_count + d_count,
        )

    except Exception as e:
        logger.error("Space objects query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
