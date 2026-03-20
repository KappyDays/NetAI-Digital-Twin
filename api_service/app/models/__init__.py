"""Pydantic request/response models for the Lakehouse API.

Static objects  -- Space-level Prim storage (all child Prims under /World/<Space>)
Dynamic objects -- Per-object Iceberg tables with fixed IoT schema
"""

from app.models.schemas import (
    # Value objects for Static Prim data
    BoundingBox,
    PrimMetadata,
    Transform,
    Vec3,
    # Static Prim Create schemas (API contract)
    StaticPrimCreate,
    StaticPrimBatchCreateRequest,
    StaticPrimCreateResponse,
    StaticPrimBatchCreateResponse,
    # Static Prim models (internal)
    StaticPrimData,
    StaticPrimDetailResponse,
    StaticPrimInsertRequest,
    StaticPrimInsertResponse,
    StaticPrimListResponse,
    StaticSpaceSummary,
    # Legacy flat Prim models (backward-compatible)
    CongestionResponse,
    DynamicInsertRequest,
    DynamicInsertResponse,
    DynamicObjectRecord,
    HealthResponse,
    PrimInsertRequest,
    PrimInsertResponse,
    PrimRecord,
    QueryRequest,
    QueryResponse,
    SpaceCongestion,
    UsdUploadResponse,
)

__all__ = [
    # Value objects
    "Vec3",
    "Transform",
    "BoundingBox",
    "PrimMetadata",
    # Static Prim Create schemas (API contract)
    "StaticPrimCreate",
    "StaticPrimBatchCreateRequest",
    "StaticPrimCreateResponse",
    "StaticPrimBatchCreateResponse",
    # Structured Static Prim models (internal)
    "StaticPrimData",
    "StaticPrimInsertRequest",
    "StaticPrimInsertResponse",
    "StaticPrimDetailResponse",
    "StaticPrimListResponse",
    "StaticSpaceSummary",
    # Legacy / flat models
    "HealthResponse",
    "PrimRecord",
    "PrimInsertRequest",
    "PrimInsertResponse",
    "DynamicObjectRecord",
    "DynamicInsertRequest",
    "DynamicInsertResponse",
    "UsdUploadResponse",
    "SpaceCongestion",
    "CongestionResponse",
    "QueryRequest",
    "QueryResponse",
]
