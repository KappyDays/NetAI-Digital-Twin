"""
Pydantic request / response schemas.

Static objects  : Space-level storage (all child Prims under a /World child)
Dynamic objects : Per-object Iceberg table with fixed schema (schema-evolution ready)

Architecture Notes
------------------
* Space = each direct child of /World in the USD scene graph.
* Static Prims are stored per-space in a single Iceberg table.
  Structured fields (transform, bbox, metadata) are serialised to
  the ``properties`` JSON column so that the Iceberg schema stays
  flat (VARCHAR) and avoids nested-type issues across Trino/Parquet.
* Transform is represented as Translate + Rotate(Euler) + Scale,
  matching the decomposed form that Isaac Sim / OpenUSD natively uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


# =====================================================================
#  Health
# =====================================================================

class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime
    version: str = "1.0.0"


# =====================================================================
#  Static Object Models -- Component Value Objects
# =====================================================================

class Vec3(BaseModel):
    """3-component vector used for translation, rotation, and scale."""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Transform(BaseModel):
    """
    Decomposed local transform of a USD Prim.

    Mirrors UsdGeom.Xformable decomposition order:
      translate -> rotate (euler XYZ in degrees) -> scale.
    For Prims without an explicit transform, all vectors default to
    identity (translate=0, rotate=0, scale=1).
    """
    translate: Vec3 = Field(default_factory=Vec3, description="Local translation (x, y, z)")
    rotate: Vec3 = Field(default_factory=Vec3, description="Local rotation in euler degrees (x, y, z)")
    scale: Vec3 = Field(
        default_factory=lambda: Vec3(x=1.0, y=1.0, z=1.0),
        description="Local scale (x, y, z)",
    )


class BoundingBox(BaseModel):
    """
    Axis-aligned bounding box (AABB) in world coordinates.

    Computed from UsdGeom.BBoxCache. If the Prim has no renderable
    geometry (e.g. a Scope or Xform grouping node), min == max == (0,0,0).
    """
    min: Vec3 = Field(default_factory=Vec3, description="Minimum corner (x, y, z)")
    max: Vec3 = Field(default_factory=Vec3, description="Maximum corner (x, y, z)")

    @property
    def center(self) -> Vec3:
        """Center point of the bounding box."""
        return Vec3(
            x=(self.min.x + self.max.x) / 2.0,
            y=(self.min.y + self.max.y) / 2.0,
            z=(self.min.z + self.max.z) / 2.0,
        )

    @property
    def extents(self) -> Vec3:
        """Half-extents (dimensions / 2) of the bounding box."""
        return Vec3(
            x=abs(self.max.x - self.min.x) / 2.0,
            y=abs(self.max.y - self.min.y) / 2.0,
            z=abs(self.max.z - self.min.z) / 2.0,
        )


class PrimMetadata(BaseModel):
    """
    Extensible metadata bag for a static USD Prim.

    Fields map to common USD metadata and Isaac Sim extension attributes.
    ``custom`` holds arbitrary key-value pairs for future schema evolution.
    """
    purpose: Optional[str] = Field(
        None, description="USD render purpose: default | render | proxy | guide",
    )
    visibility: Optional[str] = Field(
        None, description="Prim visibility: inherited | invisible",
    )
    kind: Optional[str] = Field(
        None, description="USD Model Kind: component | group | assembly | subcomponent",
    )
    material_path: Optional[str] = Field(
        None, description="Bound material Prim path (e.g. /World/Looks/Material_01)",
    )
    is_instance: bool = Field(
        False, description="True if Prim is a USD instance (PointInstancer or native)",
    )
    semantic_label: Optional[str] = Field(
        None, description="Isaac Sim semantic label (e.g. 'chair', 'wall', 'floor')",
    )
    layer_identifier: Optional[str] = Field(
        None, description="Strongest opinion layer identifier for this Prim",
    )
    custom: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for schema evolution",
    )


# =====================================================================
#  Static Object Models -- Prim Records (Space-level data -> Iceberg)
# =====================================================================

class PrimRecord(BaseModel):
    """
    Single USD Prim record from Isaac Sim stage traversal.

    This is the *flat* form used for Iceberg storage.  The structured
    ``transform``, ``bbox``, and ``metadata`` fields are packed into
    the ``properties`` JSON string before insertion.

    Accepts both ``type`` and ``object_type`` as the Prim type field
    name (via alias) for backward compatibility.
    """
    prim_path: str = Field(..., description="Full USD Prim path (e.g. /World/Room_A/Chair_01)")
    object_type: str = Field(..., alias="type", description="Prim type name (e.g. Xform, Mesh, Scope)")
    properties: str = Field(
        "{}",
        description="JSON string containing attributes, relationships, and metadata",
    )

    model_config = {"populate_by_name": True}


class StaticPrimData(BaseModel):
    """
    Rich, structured representation of a static USD Prim.

    This is the *structured* form that clients (Isaac Sim Extension, Web
    Dashboard) exchange with the API.  Conversion to/from the flat
    ``PrimRecord`` (Iceberg row) is handled by helper methods.

    Fields
    ------
    prim_path : str
        Full USD Prim path relative to the stage root.
    object_type : str
        USD Prim type schema name (Xform, Mesh, Scope, Camera, ...).
    space_id : str | None
        Derived from the path -- the direct /World child that owns this Prim.
    parent_path : str | None
        Immediate parent Prim path.  Useful for hierarchy reconstruction.
    transform : Transform
        Local transform (translate, rotate, scale).
    bbox : BoundingBox
        World-space axis-aligned bounding box.
    metadata : PrimMetadata
        Extensible metadata bag.
    child_count : int
        Number of direct children of this Prim in the scene graph.
    """
    prim_path: str = Field(..., description="Full USD Prim path (e.g. /World/Room_A/Chair_01)")
    object_type: str = Field(..., description="Prim type name (e.g. Xform, Mesh, Scope)")
    space_id: Optional[str] = Field(
        None,
        description="Auto-derived space id from /World/<SpaceName>/... path pattern",
    )
    parent_path: Optional[str] = Field(
        None,
        description="Parent Prim path for hierarchy reconstruction",
    )
    transform: Transform = Field(default_factory=Transform, description="Local transform")
    bbox: BoundingBox = Field(default_factory=BoundingBox, description="World-space AABB")
    metadata: PrimMetadata = Field(default_factory=PrimMetadata, description="Extensible metadata")
    child_count: int = Field(0, ge=0, description="Number of direct child Prims")

    # -- Derived fields ------------------------------------------------

    @model_validator(mode="after")
    def _derive_space_id(self) -> "StaticPrimData":
        """Auto-fill space_id from prim_path if not explicitly provided."""
        if self.space_id is None:
            parts = self.prim_path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "World":
                self.space_id = parts[1]
        return self

    # -- Serialisation helpers -----------------------------------------

    def to_prim_record(self) -> PrimRecord:
        """
        Flatten to a PrimRecord suitable for Iceberg insertion.

        Transform, bbox, metadata, and other structured fields are
        packed into the ``properties`` JSON column.
        """
        props: Dict[str, Any] = {
            "transform": self.transform.model_dump(),
            "bbox": self.bbox.model_dump(),
            "metadata": self.metadata.model_dump(),
            "parent_path": self.parent_path,
            "child_count": self.child_count,
        }
        return PrimRecord(
            prim_path=self.prim_path,
            type=self.object_type,
            properties=json.dumps(props, default=str),
        )

    @classmethod
    def from_prim_record(
        cls, record: PrimRecord, space_id: Optional[str] = None,
    ) -> "StaticPrimData":
        """Reconstruct a StaticPrimData from a flat PrimRecord (Iceberg row)."""
        try:
            props = json.loads(record.properties) if record.properties else {}
        except (json.JSONDecodeError, TypeError):
            props = {}

        transform = Transform(**props["transform"]) if "transform" in props else Transform()
        bbox = BoundingBox(**props["bbox"]) if "bbox" in props else BoundingBox()
        metadata = PrimMetadata(**props["metadata"]) if "metadata" in props else PrimMetadata()

        return cls(
            prim_path=record.prim_path,
            object_type=record.object_type,
            space_id=space_id,
            parent_path=props.get("parent_path"),
            transform=transform,
            bbox=bbox,
            metadata=metadata,
            child_count=props.get("child_count", 0),
        )

    @classmethod
    def from_row(cls, row: List[Any], columns: List[str]) -> "StaticPrimData":
        """
        Reconstruct from a Trino query result row + column names.

        Expected columns: prim_path, type, properties, space_id, ingested_at
        """
        col_map = {col: idx for idx, col in enumerate(columns)}
        prim_path = row[col_map["prim_path"]]
        object_type = row[col_map.get("type", col_map.get("object_type", 1))]
        properties_str = row[col_map.get("properties", 2)] if "properties" in col_map else "{}"
        space_id_val = row[col_map["space_id"]] if "space_id" in col_map else None

        record = PrimRecord(
            prim_path=prim_path,
            type=object_type,
            properties=properties_str or "{}",
        )
        return cls.from_prim_record(record, space_id=space_id_val)


# =====================================================================
#  Static Object Request / Response Schemas
# =====================================================================

class StaticPrimInsertRequest(BaseModel):
    """
    Batch insert of structured static Prim records.

    Used by Isaac Sim Extension to push scene data with full
    transform/bbox/metadata to the Lakehouse.
    """
    space_id: Optional[str] = Field(
        None, description="Override space_id for all records in this batch",
    )
    records: List[StaticPrimData] = Field(
        ..., min_length=1, description="Prim records to insert",
    )


class StaticPrimInsertResponse(BaseModel):
    """Response after successfully inserting static Prim records."""
    inserted: int = Field(..., description="Number of records inserted")
    table: str = Field(..., description="Fully-qualified Iceberg table name")
    space_ids: List[str] = Field(
        default_factory=list, description="Distinct space_ids in this batch",
    )
    message: str = "ok"


class StaticPrimDetailResponse(BaseModel):
    """Single Prim detail -- returned when querying by exact prim_path."""
    prim: StaticPrimData
    ingested_at: Optional[datetime] = None


class StaticPrimListResponse(BaseModel):
    """
    Paginated list of structured static Prim records.

    Used by Extension UI and Web Dashboard for space exploration
    and scene graph browsing.
    """
    prims: List[StaticPrimData] = Field(default_factory=list)
    total_count: int = Field(0, description="Total matching records (before pagination)")
    page_size: int = Field(0, description="Requested page size")
    offset: int = Field(0, description="Current offset")
    space_id: Optional[str] = Field(None, description="Space filter applied (if any)")


class StaticSpaceSummary(BaseModel):
    """
    Aggregated summary of a single space, including type distribution
    and bounding-box envelope -- suitable for congestion visualisation.
    """
    space_id: str
    prim_count: int = 0
    type_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of Prims per USD type within this space",
    )
    bbox_envelope: Optional[BoundingBox] = Field(
        None,
        description="World-space AABB enclosing all Prims in this space",
    )
    last_ingested: Optional[datetime] = None


# =====================================================================
#  Static Object Create Schemas (API Request / Response)
# =====================================================================

class StaticPrimCreate(BaseModel):
    """
    Request schema for creating a single static USD Prim record.

    This is the primary **ingestion contract** between clients (Isaac Sim
    Extension, automation scripts) and the Lakehouse API.  It uses
    ``prim_type`` (not ``object_type``) to align with USD terminology
    and provides structured sub-objects for transform, bbox, and
    extensible properties.

    Conversion
    ----------
    ``to_static_prim_data()`` → ``StaticPrimData`` (internal model)
    ``to_prim_record()``      → ``PrimRecord``     (flat Iceberg row)

    Field Summary
    -------------
    prim_path   : Full USD Prim path (e.g. /World/Room_A/Chair_01)
    prim_type   : USD type schema name (Mesh, Xform, Scope, Camera, …)
    space_id    : Optional override; auto-derived from prim_path if omitted
    parent_path : Immediate parent path for hierarchy reconstruction
    transform   : Decomposed local transform (translate, rotate, scale)
    bbox        : World-space axis-aligned bounding box
    properties  : Extensible metadata bag (purpose, visibility, material, …)
    child_count : Number of direct children in the scene graph
    """

    prim_path: str = Field(
        ...,
        min_length=1,
        description="Full USD Prim path (e.g. /World/Room_A/Chair_01)",
        examples=["/World/Room_A/Chair_01", "/World/Lab_B/Rack/Shelf_03"],
    )
    prim_type: str = Field(
        ...,
        min_length=1,
        description=(
            "USD Prim type schema name. Common values: "
            "Xform, Mesh, Scope, Camera, DistantLight, Material, Shader"
        ),
        examples=["Mesh", "Xform", "Scope"],
    )
    space_id: Optional[str] = Field(
        None,
        description=(
            "Space identifier (direct /World child). "
            "Auto-derived from prim_path if omitted."
        ),
    )
    parent_path: Optional[str] = Field(
        None,
        description="Parent Prim path for scene-graph hierarchy reconstruction",
        examples=["/World/Room_A"],
    )
    transform: Transform = Field(
        default_factory=Transform,
        description="Local transform: translate, rotate (euler XYZ°), scale",
    )
    bbox: BoundingBox = Field(
        default_factory=BoundingBox,
        description="World-space axis-aligned bounding box (AABB)",
    )
    properties: PrimMetadata = Field(
        default_factory=PrimMetadata,
        description=(
            "Extensible metadata: purpose, visibility, kind, material_path, "
            "semantic_label, is_instance, layer_identifier, custom dict"
        ),
    )
    child_count: int = Field(
        0, ge=0,
        description="Number of direct child Prims in the scene graph",
    )

    # -- Derived helpers -----------------------------------------------

    @model_validator(mode="after")
    def _derive_space_id(self) -> "StaticPrimCreate":
        """Auto-fill space_id from prim_path when not explicitly provided."""
        if self.space_id is None:
            parts = self.prim_path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "World":
                self.space_id = parts[1]
        return self

    # -- Conversion helpers --------------------------------------------

    def to_static_prim_data(self) -> StaticPrimData:
        """Convert to the internal StaticPrimData model."""
        return StaticPrimData(
            prim_path=self.prim_path,
            object_type=self.prim_type,
            space_id=self.space_id,
            parent_path=self.parent_path,
            transform=self.transform,
            bbox=self.bbox,
            metadata=self.properties,
            child_count=self.child_count,
        )

    def to_prim_record(self) -> PrimRecord:
        """Convert directly to a flat PrimRecord for Iceberg insertion."""
        return self.to_static_prim_data().to_prim_record()


class StaticPrimBatchCreateRequest(BaseModel):
    """
    Batch creation request for static USD Prim records.

    Used by Isaac Sim Extension to push full scene snapshots to the
    Lakehouse in a single API call.
    """
    space_id: Optional[str] = Field(
        None,
        description="Override space_id for all records in this batch",
    )
    prims: List[StaticPrimCreate] = Field(
        ...,
        min_length=1,
        description="One or more Prim records to create",
    )

    @model_validator(mode="after")
    def _apply_space_override(self) -> "StaticPrimBatchCreateRequest":
        """If top-level space_id is set, apply to all prims lacking one."""
        if self.space_id:
            for prim in self.prims:
                if prim.space_id is None:
                    prim.space_id = self.space_id
        return self


class StaticPrimCreateResponse(BaseModel):
    """Response after creating a single static Prim record."""
    prim_path: str = Field(..., description="Created Prim path")
    prim_type: str = Field(..., description="USD Prim type")
    space_id: Optional[str] = Field(None, description="Resolved space identifier")
    table: str = Field(..., description="Fully-qualified Iceberg table name")
    message: str = "ok"


class StaticPrimBatchCreateResponse(BaseModel):
    """Response after batch-creating static Prim records."""
    inserted: int = Field(..., description="Number of records successfully inserted")
    table: str = Field(..., description="Fully-qualified Iceberg table name")
    space_ids: List[str] = Field(
        default_factory=list,
        description="Distinct space_ids in this batch",
    )
    failed: List[str] = Field(
        default_factory=list,
        description="Prim paths that failed insertion (if any)",
    )
    message: str = "ok"


# -- Legacy aliases (backward-compatible) ------------------------------

class PrimInsertRequest(BaseModel):
    """Batch insert of flat static Prim records (legacy/simple form)."""
    records: List[PrimRecord]


class PrimInsertResponse(BaseModel):
    inserted: int
    table: str
    message: str = "ok"


class SpaceOverwriteRequest(BaseModel):
    """Request to replace ALL prims for a specific space."""
    records: List[PrimRecord] = Field(
        default_factory=list,
        description="New prim records for this space (empty = delete all)",
    )


class SpaceOverwriteResponse(BaseModel):
    """Response after space-level prim overwrite."""
    space_id: str
    inserted: int
    table: str
    message: str = "ok"


class StaticTableInfoResponse(BaseModel):
    """Metadata about the static_prims Iceberg table."""
    status: str
    identifier: str
    schema_fields: Optional[List[dict]] = None
    partition_spec: Optional[str] = None
    snapshot_count: Optional[int] = None
    current_snapshot_id: Optional[int] = None
    location: Optional[str] = None
    message: Optional[str] = None


# =====================================================================
#  Dynamic Object Models (per-object Iceberg table)
# =====================================================================

class DynamicObjectRecord(BaseModel):
    """A single IoT / tracking data point for a dynamic object."""
    object_id: str = Field(..., description="Unique dynamic object identifier")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    pos_x: float = Field(0.0, description="X position in world coordinates")
    pos_y: float = Field(0.0, description="Y position in world coordinates")
    pos_z: float = Field(0.0, description="Z position in world coordinates")
    rot_x: float = Field(0.0, description="Rotation X (euler degrees)")
    rot_y: float = Field(0.0, description="Rotation Y (euler degrees)")
    rot_z: float = Field(0.0, description="Rotation Z (euler degrees)")
    speed: float = Field(0.0, description="Speed m/s")
    space_id: str = Field("", description="Current space/zone the object is in")
    properties: str = Field("{}", description="Extra properties as JSON string")


class DynamicInsertRequest(BaseModel):
    records: list[DynamicObjectRecord]


class DynamicInsertResponse(BaseModel):
    inserted: int
    table: str
    object_id: str
    message: str = "ok"


class DynamicBatchInsertResponse(BaseModel):
    """Response for batch sensor data insertion via Trino SQL."""
    inserted: int
    table: str
    object_id: str
    chunk_count: int = 1
    message: str = "ok"


class SensorInsertStatsResponse(BaseModel):
    """Statistics about inserted sensor data for a dynamic object."""
    object_id: str
    table_name: str
    record_count: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    latest_position: Optional[dict] = None


class MultiObjectInsertResult(BaseModel):
    """Per-object result within a multi-object batch insert."""
    inserted: int
    table: str
    object_id: str
    chunk_count: int = 1


class MultiObjectInsertResponse(BaseModel):
    """Response for multi-object batch sensor data insertion."""
    total_inserted: int
    object_count: int
    results: list[MultiObjectInsertResult]
    errors: list[dict] = Field(default_factory=list)
    message: str = "ok"


# =====================================================================
#  USD Upload
# =====================================================================

class UsdUploadResponse(BaseModel):
    filename: str
    s3_key: str
    bucket: str
    message: str = "ok"


# =====================================================================
#  Congestion / Visualization
# =====================================================================

class SpaceCongestion(BaseModel):
    """Congestion data for a single space at a point in time."""
    space_id: str
    object_count: int = 0
    congestion_level: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Normalized congestion 0.0 (empty) -- 1.0 (full)",
    )
    timestamp: datetime


class CongestionResponse(BaseModel):
    spaces: list[SpaceCongestion]
    total_objects: int
    snapshot_time: datetime


class CongestionGridCell(BaseModel):
    """Single cell in the 2D congestion grid."""
    row: int = Field(..., ge=0, description="Grid row index (Y-axis)")
    col: int = Field(..., ge=0, description="Grid column index (X-axis)")
    value: float = Field(0.0, ge=0.0, description="Congestion value (object count or normalized)")
    x_min: float = Field(..., description="World X-coordinate of cell left edge")
    x_max: float = Field(..., description="World X-coordinate of cell right edge")
    y_min: float = Field(..., description="World Y-coordinate of cell bottom edge")
    y_max: float = Field(..., description="World Y-coordinate of cell top edge")
    object_ids: list[str] = Field(default_factory=list, description="Object IDs in this cell")


class CongestionGridConfig(BaseModel):
    """Configuration for the 2D congestion grid."""
    x_min: float = Field(-50.0, description="World X-coordinate minimum bound")
    x_max: float = Field(50.0, description="World X-coordinate maximum bound")
    y_min: float = Field(-50.0, description="World Y-coordinate minimum bound")
    y_max: float = Field(50.0, description="World Y-coordinate maximum bound")
    rows: int = Field(20, ge=1, le=200, description="Number of grid rows")
    cols: int = Field(20, ge=1, le=200, description="Number of grid columns")
    cell_width: float = Field(0.0, description="Computed cell width in world units")
    cell_height: float = Field(0.0, description="Computed cell height in world units")


class CongestionGridResponse(BaseModel):
    """2D grid-based congestion data for heatmap visualization."""
    config: CongestionGridConfig
    cells: list[CongestionGridCell] = Field(
        default_factory=list, description="Non-empty grid cells with congestion values",
    )
    grid: list[list[float]] = Field(
        default_factory=list,
        description="Full 2D grid matrix [rows][cols] with congestion values",
    )
    max_value: float = Field(0.0, description="Maximum congestion value in the grid")
    total_objects: int = Field(0, description="Total dynamic objects counted")
    snapshot_time: datetime


# =====================================================================
#  Query helpers
# =====================================================================

class QueryRequest(BaseModel):
    sql: str = Field(..., description="Trino SQL query")


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


# =====================================================================
#  Static Query Models
# =====================================================================

class StaticQueryParams(BaseModel):
    """Parameters for querying static Prim records."""
    space_id: Optional[str] = Field(None, description="Filter by space (direct /World child)")
    prim_type: Optional[str] = Field(None, description="Filter by Prim type (e.g. Mesh, Xform)")
    prim_path: Optional[str] = Field(None, description="Filter by prim_path (exact or prefix)")
    exact_path: bool = Field(True, description="If True, match exact path; if False, prefix match")
    limit: int = Field(10000, ge=1, le=100000, description="Max rows to return")
    offset: int = Field(0, ge=0, description="Rows to skip for pagination")


class StaticCountResponse(BaseModel):
    """Total and per-space Prim counts."""
    total_count: int
    space_counts: dict[str, int] = Field(default_factory=dict)
    space_count: int = 0


class StaticSpaceInfo(BaseModel):
    """Aggregated info for a single space."""
    space_id: str
    prim_count: int
    type_count: int
    last_ingested: Optional[str] = None


class StaticSpacesResponse(BaseModel):
    """List of all spaces with aggregated metadata."""
    spaces: list[StaticSpaceInfo]
    total_spaces: int


class StaticTypeSummaryItem(BaseModel):
    """Count of prims per type."""
    type: str
    prim_count: int


class StaticTypeSummaryResponse(BaseModel):
    """Breakdown of Prim types in the scene or a space."""
    types: list[StaticTypeSummaryItem]
    total_types: int


# =====================================================================
#  Dynamic Object Query Models
# =====================================================================

class DynamicObjectInfo(BaseModel):
    """Metadata for a registered dynamic object."""
    object_id: str
    table_name: str
    record_count: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class DynamicObjectListResponse(BaseModel):
    objects: list[DynamicObjectInfo]
    total: int


class DynamicTimeRangeRequest(BaseModel):
    """Query dynamic object records within a time range with pagination and filtering."""
    object_id: str = Field(..., description="Dynamic object identifier")
    start_time: datetime = Field(..., description="Start of time window (inclusive)")
    end_time: datetime = Field(..., description="End of time window (inclusive)")
    limit: int = Field(10000, ge=1, le=100000, description="Max rows to return")
    offset: int = Field(0, ge=0, description="Number of rows to skip for pagination")
    order: str = Field("ASC", description="Sort order for timestamp: ASC or DESC")
    speed_min: Optional[float] = Field(None, ge=0.0, description="Filter: minimum speed (m/s)")
    speed_max: Optional[float] = Field(None, ge=0.0, description="Filter: maximum speed (m/s)")
    space_id: Optional[str] = Field(None, description="Filter: only records in this space")


class DynamicSpaceQueryRequest(BaseModel):
    """Query dynamic objects by space, optionally filtered by time range."""
    space_id: str = Field(..., description="Space/zone identifier")
    start_time: Optional[datetime] = Field(None, description="Optional start of time window")
    end_time: Optional[datetime] = Field(None, description="Optional end of time window")
    limit: int = Field(10000, ge=1, le=100000, description="Max rows to return")
    offset: int = Field(0, ge=0, description="Number of rows to skip for pagination")
    object_type: Optional[str] = Field(None, description="Filter by dynamic object_type column")


class DynamicTrajectoryRequest(BaseModel):
    """Query movement trajectory of a dynamic object."""
    object_id: str = Field(..., description="Dynamic object identifier")
    start_time: datetime = Field(..., description="Start of time window")
    end_time: datetime = Field(..., description="End of time window")
    sample_interval_seconds: Optional[int] = Field(
        None, ge=1,
        description="If set, downsample trajectory into N-second buckets with averaged positions",
    )
    limit: int = Field(5000, ge=1, le=50000, description="Max trajectory points")
    offset: int = Field(0, ge=0, description="Number of rows to skip for pagination")


class DynamicSpatialRangeRequest(BaseModel):
    """Query dynamic objects within a spatial bounding box."""
    x_min: float = Field(..., description="Minimum X coordinate")
    x_max: float = Field(..., description="Maximum X coordinate")
    y_min: float = Field(..., description="Minimum Y coordinate")
    y_max: float = Field(..., description="Maximum Y coordinate")
    z_min: Optional[float] = Field(None, description="Optional minimum Z coordinate")
    z_max: Optional[float] = Field(None, description="Optional maximum Z coordinate")
    start_time: Optional[datetime] = Field(None, description="Optional start of time window")
    end_time: Optional[datetime] = Field(None, description="Optional end of time window")
    limit: int = Field(10000, ge=1, le=100000, description="Max rows to return")
    offset: int = Field(0, ge=0, description="Number of rows to skip for pagination")


class PaginatedQueryResponse(BaseModel):
    """Query response with pagination metadata for dynamic object queries."""
    columns: list[str]
    rows: list[list[Any]]
    row_count: int = Field(..., description="Number of rows in this page")
    offset: int = Field(0, description="Current offset (rows skipped)")
    limit: int = Field(10000, description="Page size used for this query")
    has_more: bool = Field(False, description="True if more rows exist beyond this page")
    total_estimate: Optional[int] = Field(
        None,
        description="Estimated total matching rows (may be approximate for large datasets)",
    )


class CongestionTimeseriesRequest(BaseModel):
    """Request time-series congestion data for dashboard visualization."""
    space_id: Optional[str] = Field(None, description="Optional space filter (all spaces if omitted)")
    start_time: Optional[datetime] = Field(None, description="Optional start of time window")
    end_time: Optional[datetime] = Field(None, description="Optional end of time window")
    bucket_seconds: int = Field(60, ge=1, le=86400, description="Time bucket size in seconds")
    limit: int = Field(1000, ge=1, le=50000, description="Max result rows")


# =====================================================================
#  Space Drill-Down (Object-Level Detail View)
# =====================================================================

class DrilldownStaticObject(BaseModel):
    """A single static object within a space, extracted from Iceberg data."""
    prim_path: str = Field(..., description="Full USD Prim path")
    object_type: str = Field(..., description="USD Prim type (Mesh, Xform, etc.)")
    parent_path: Optional[str] = Field(None, description="Parent Prim path")
    position: Optional[Vec3] = Field(None, description="Local translation (from properties JSON)")
    rotation: Optional[Vec3] = Field(None, description="Local rotation euler degrees")
    scale: Optional[Vec3] = Field(None, description="Local scale")
    visibility: Optional[str] = Field(None, description="Prim visibility")
    material_path: Optional[str] = Field(None, description="Bound material path")
    semantic_label: Optional[str] = Field(None, description="Semantic label if any")
    child_count: int = Field(0, description="Number of direct children")
    depth: int = Field(0, description="Hierarchy depth relative to space root")
    properties_raw: str = Field("{}", description="Raw properties JSON for advanced inspection")


class DrilldownDynamicObject(BaseModel):
    """A dynamic object currently or recently in a space, with latest state."""
    object_id: str = Field(..., description="Dynamic object identifier")
    position: Vec3 = Field(default_factory=Vec3, description="Latest position (x, y, z)")
    rotation: Vec3 = Field(default_factory=Vec3, description="Latest rotation euler degrees")
    speed: float = Field(0.0, description="Latest speed (m/s)")
    space_id: str = Field("", description="Current space_id")
    last_seen: Optional[str] = Field(None, description="Timestamp of latest record")
    status: str = Field(
        "unknown",
        description="Object status: active (seen <60s ago), idle (60-300s), stale (>300s), unknown",
    )
    properties: str = Field("{}", description="Extra properties JSON")


class SpaceDrilldownResponse(BaseModel):
    """
    Full drill-down response for a single space.

    Contains both static scene objects (from Iceberg static table)
    and dynamic IoT/tracked objects (from per-object dynamic tables),
    along with aggregated space summary metadata.
    """
    space_id: str = Field(..., description="The queried space identifier")
    # Summary
    static_count: int = Field(0, description="Number of static Prims in this space")
    dynamic_count: int = Field(0, description="Number of dynamic objects in this space")
    type_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of static Prims per USD type",
    )
    # Object lists
    static_objects: List[DrilldownStaticObject] = Field(
        default_factory=list,
        description="Static Prim objects in this space (scene graph)",
    )
    dynamic_objects: List[DrilldownDynamicObject] = Field(
        default_factory=list,
        description="Dynamic objects currently/recently in this space",
    )
    # Metadata
    last_static_ingestion: Optional[str] = Field(
        None, description="Timestamp of last static data ingestion",
    )
    snapshot_time: Optional[str] = Field(
        None, description="Server timestamp when this response was generated",
    )
