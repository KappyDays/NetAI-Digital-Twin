"""
Aggregated v1 API router.

Mounts all v1 sub-routers under /api/v1 prefix.
"""

from fastapi import APIRouter

from app.api.v1 import health, query, upload
from app.routers.entities import router as entities_router
from app.routers.raw_backup import router as raw_backup_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(upload.router)        # /api/v1/upload-usd (Task 2 USD upload)
api_router.include_router(query.router)         # /api/v1/query (ad-hoc Trino SQL)
api_router.include_router(entities_router)      # /api/v1/entities/* (Task 2/3)
api_router.include_router(raw_backup_router)    # /api/v1/raw-backup/* (Task 1)
