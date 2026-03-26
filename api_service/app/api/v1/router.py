"""
Aggregated v1 API router.

Mounts all v1 sub-routers under /api/v1 prefix.
"""

from fastapi import APIRouter

from app.api.v1 import dynamic, health, prims, query, spaces, static, upload
from app.routers.dynamic_objects import router as dynamic_objects_router
from app.routers.entities import router as entities_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(prims.router)       # POST /api/v1/prims  (primary ingestion)
api_router.include_router(static.router)       # /api/v1/static/*    (queries + write alias)
api_router.include_router(dynamic.router)      # /api/v1/dynamic/*   (legacy ingest + queries)
api_router.include_router(dynamic_objects_router)  # /api/v1/dynamic-objects/* (tables + sensor-data)
api_router.include_router(spaces.router)        # /api/v1/spaces/*    (congestion summary + per-space objects)
api_router.include_router(upload.router)
api_router.include_router(query.router)
api_router.include_router(entities_router)   # /api/v1/entities/* + /api/v1/dynamic/sample-ingest
