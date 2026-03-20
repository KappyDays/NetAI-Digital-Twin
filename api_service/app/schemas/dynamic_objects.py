"""
Pydantic request / response schemas for Dynamic object endpoints.

Dynamic objects are IoT / tracking entities (e.g., UWB-tagged workers, AGVs,
mobile robots) whose position and state change over time. Each dynamic object
gets its own Iceberg table: ``dynamic_<object_id>`` with a fixed schema
designed for schema evolution compatibility.

Fixed Iceberg column schema (per-object table):
    object_id   VARCHAR  NOT NULL  -- Unique identifier (matches table suffix)
    timestamp   TIMESTAMP(6) NOT NULL  -- Observation time (microsecond precision)
    pos_x       DOUBLE            -- X position in world coordinates
    pos_y       DOUBLE            -- Y position in world coordinates
    pos_z       DOUBLE            -- Z position in world coordinates
    rot_x       DOUBLE            -- Euler rotation X (degrees)
    rot_y       DOUBLE            -- Euler rotation Y (degrees)
    rot_z       DOUBLE            -- Euler rotation Z (degrees)
    speed       DOUBLE            -- Instantaneous speed (m/s)
    space_id    VARCHAR           -- Current /World child space the object is in
    properties  VARCHAR           -- Extra properties as JSON string (extensible)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ===================================================================
#  Table Creation Models
# ===================================================================

class CreateDynamicTableRequest(BaseModel):
    """Request to explicitly create a dynamic object's Iceberg table.

    Use this *before* any data ingestion when you want to pre-provision
    the table (e.g., during Extension startup or deployment automation).
    If the table already exists, the operation is idempotent.
    """

    object_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Unique identifier for the dynamic object. "
            "Used to derive table name: dynamic_<sanitised_object_id>. "
            "Allowed characters: alphanumeric, hyphens, underscores."
        ),
        examples=["worker_01", "agv-alpha", "uwb_tag_0042"],
    )
    description: Optional[str] = Field(
        None,
        max_length=512,
        description="Optional human-readable description of the dynamic object.",
        examples=["UWB-tagged warehouse worker #1"],
    )

    @field_validator("object_id")
    @classmethod
    def validate_object_id(cls, v: str) -> str:
        """Ensure object_id contains only safe characters for table naming."""
        sanitised = v.replace("-", "_").replace(" ", "_")
        if not sanitised.replace("_", "").isalnum():
            raise ValueError(
                "object_id must contain only alphanumeric characters, "
                "hyphens, or underscores."
            )
        return v


class RegisterDynamicObjectRequest(BaseModel):
    """Request body for POST /api/v1/dynamic-objects/{object_type}.

    Registers a new dynamic object of a specific type by creating its
    per-object Iceberg table with the appropriate type-aware schema.
    The ``object_type`` is provided as a path parameter, while this body
    contains the object's identity and optional metadata.

    Partitioning strategy applied to the created table:
      - day(timestamp): daily partitions for efficient time-range queries
      - space_id: spatial partitions for per-zone congestion analysis
    """

    object_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Unique identifier for the dynamic object. "
            "Derives the table name: dynamic_<sanitised_object_id>."
        ),
        examples=["worker_01", "agv-alpha", "uwb_tag_0042"],
    )
    description: Optional[str] = Field(
        None,
        max_length=512,
        description="Optional human-readable description of the dynamic object.",
        examples=["UWB-tagged warehouse worker in zone A"],
    )
    metadata: Optional[dict[str, Any]] = Field(
        None,
        description=(
            "Optional metadata dict stored as reference. "
            "Not persisted in Iceberg but returned in the response."
        ),
        examples=[{"zone": "Assembly_Line", "department": "Manufacturing"}],
    )

    @field_validator("object_id")
    @classmethod
    def validate_object_id(cls, v: str) -> str:
        """Ensure object_id contains only safe characters for table naming."""
        sanitised = v.replace("-", "_").replace(" ", "_")
        if not sanitised.replace("_", "").isalnum():
            raise ValueError(
                "object_id must contain only alphanumeric characters, "
                "hyphens, or underscores."
            )
        return v


class DynamicTableInfo(BaseModel):
    """Metadata about a created/existing dynamic table."""

    object_id: str = Field(..., description="Original object identifier")
    table_name: str = Field(
        ..., description="Iceberg table name (e.g., dynamic_worker_01)"
    )
    fully_qualified: str = Field(
        ...,
        description="Fully-qualified Trino path: catalog.namespace.table",
    )
    object_type: str = Field(
        "generic",
        description="Object type used for schema selection (e.g., person, robot, vehicle)",
    )
    columns: list[str] = Field(
        default_factory=lambda: [
            "object_id",
            "timestamp",
            "pos_x",
            "pos_y",
            "pos_z",
            "rot_x",
            "rot_y",
            "rot_z",
            "speed",
            "space_id",
            "properties",
        ],
        description="Column names in the table schema",
    )
    partitioning: list[str] = Field(
        default_factory=lambda: ["day(timestamp)", "space_id"],
        description="Iceberg partitioning specification",
    )


class RegisterDynamicObjectResponse(BaseModel):
    """Response after registering a dynamic object via POST /{object_type}."""

    created: bool = Field(
        ..., description="True if newly created; False if already existed"
    )
    table: DynamicTableInfo
    object_type: str = Field(
        ..., description="Object type from path parameter"
    )
    schema_columns: list[dict[str, str]] = Field(
        default_factory=list,
        description="Full column definitions (name + data_type) of the created table",
    )
    partitioning: list[str] = Field(
        default_factory=lambda: ["day(timestamp)", "space_id"],
        description="Iceberg partitioning strategy applied to the table",
    )
    message: str = "ok"


class CreateDynamicTableResponse(BaseModel):
    """Response after creating (or confirming) a dynamic object table."""

    created: bool = Field(
        ..., description="True if newly created; False if already existed"
    )
    table: DynamicTableInfo
    message: str = "ok"


# ===================================================================
#  Sensor Data Ingestion Models
# ===================================================================

class SensorDataRecord(BaseModel):
    """A single IoT / tracking / sensor data point for a dynamic object.

    Maps 1:1 to a row in the per-object Iceberg table.
    All positional/rotational fields default to 0.0 so partial
    updates (e.g., position-only from UWB) are supported.
    """

    object_id: str = Field(
        ...,
        min_length=1,
        description="Unique dynamic object identifier (must match table)",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Observation timestamp (UTC). Auto-filled if omitted.",
    )
    pos_x: float = Field(0.0, description="X position in world coordinates")
    pos_y: float = Field(0.0, description="Y position in world coordinates")
    pos_z: float = Field(0.0, description="Z position in world coordinates")
    rot_x: float = Field(0.0, description="Rotation X (euler degrees)")
    rot_y: float = Field(0.0, description="Rotation Y (euler degrees)")
    rot_z: float = Field(0.0, description="Rotation Z (euler degrees)")
    speed: float = Field(0.0, ge=0.0, description="Instantaneous speed (m/s)")
    space_id: str = Field(
        "",
        description=(
            "Current space/zone ID (direct /World child) the object occupies. "
            "Used for congestion computation."
        ),
    )
    properties: str = Field(
        "{}",
        description=(
            "Extra properties as a JSON string. Allows schema-evolution-safe "
            "storage of sensor-specific fields (e.g., battery_level, rssi)."
        ),
    )

    @field_validator("properties")
    @classmethod
    def validate_properties_json(cls, v: str) -> str:
        """Ensure properties is valid JSON."""
        import json

        try:
            json.loads(v)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("properties must be a valid JSON string")
        return v


class SensorInsertRequest(BaseModel):
    """Batch insert request for sensor / IoT data.

    All records in a single request MUST belong to the same object_id.
    The table is auto-created if it doesn't already exist (idempotent).
    """

    object_id: str = Field(
        ...,
        min_length=1,
        description=(
            "Target dynamic object ID. All records must match this ID. "
            "The per-object Iceberg table is auto-created if needed."
        ),
    )
    records: list[SensorDataRecord] = Field(
        ...,
        min_length=1,
        description="One or more sensor data records to insert.",
    )

    @field_validator("records")
    @classmethod
    def validate_consistent_object_id(
        cls, v: list[SensorDataRecord], info
    ) -> list[SensorDataRecord]:
        """Ensure all records reference the same object_id as the request."""
        # info.data may not have object_id yet during validation order,
        # so we check inter-record consistency here. The router will
        # verify against request.object_id.
        if not v:
            return v
        ids = {r.object_id for r in v}
        if len(ids) > 1:
            raise ValueError(
                f"All records must have the same object_id. Found: {ids}"
            )
        return v


class SensorInsertResponse(BaseModel):
    """Response after inserting sensor data records."""

    inserted: int = Field(..., description="Number of records successfully inserted")
    table: str = Field(
        ..., description="Iceberg table name used (e.g., dynamic_worker_01)"
    )
    object_id: str = Field(..., description="Dynamic object identifier")
    first_timestamp: Optional[str] = Field(
        None, description="Earliest timestamp in the batch (ISO format)"
    )
    last_timestamp: Optional[str] = Field(
        None, description="Latest timestamp in the batch (ISO format)"
    )
    message: str = "ok"


# ===================================================================
#  Legacy-compatible aliases (used by existing dynamic.py)
# ===================================================================
# These maintain backward compatibility with the schemas imported
# by app/api/v1/dynamic.py from app/models/schemas.py.

class DynamicObjectRecord(BaseModel):
    """Alias for SensorDataRecord — backward compat with existing code."""

    object_id: str = Field(..., description="Unique dynamic object identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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
    """Legacy batch insert request (used by existing /dynamic/ingest)."""

    records: list[DynamicObjectRecord]


class DynamicInsertResponse(BaseModel):
    """Legacy insert response."""

    inserted: int
    table: str
    object_id: str
    message: str = "ok"


class DynamicBatchInsertResponse(BaseModel):
    """Response for batch insert across multiple objects (future use)."""

    total_inserted: int = Field(..., description="Total records inserted across all objects")
    objects: list[SensorInsertResponse] = Field(
        ..., description="Per-object insertion results"
    )
    message: str = "ok"


# ===================================================================
#  Object-Type-Aware Sensor Data INSERT Models (Trino SQL path)
# ===================================================================

class SensorDataPoint(BaseModel):
    """A single sensor/IoT data point for Trino SQL INSERT.

    Designed for the ``POST /api/v1/dynamic-objects/{object_type}/data``
    endpoint which inserts data via Trino SQL (not PyIceberg).

    All positional/rotational fields default to 0.0 so partial updates
    (e.g., position-only from UWB, rotation-only from IMU) are supported.
    """

    object_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Unique dynamic object identifier (must match table).",
        examples=["worker_01", "agv-alpha"],
    )
    timestamp: Optional[datetime] = Field(
        None,
        description=(
            "Observation timestamp (UTC). If omitted, the server sets it "
            "to the current UTC time at ingestion."
        ),
    )
    pos_x: float = Field(0.0, description="X position in world coordinates")
    pos_y: float = Field(0.0, description="Y position in world coordinates")
    pos_z: float = Field(0.0, description="Z position in world coordinates")
    rot_x: float = Field(0.0, description="Rotation X (euler degrees)")
    rot_y: float = Field(0.0, description="Rotation Y (euler degrees)")
    rot_z: float = Field(0.0, description="Rotation Z (euler degrees)")
    speed: float = Field(0.0, ge=0.0, description="Instantaneous speed (m/s)")
    space_id: str = Field(
        "",
        description="Current space/zone the object occupies (/World child).",
    )
    properties: str = Field(
        "{}",
        description="Extra properties as JSON string (schema-evolution-safe).",
    )

    @field_validator("properties")
    @classmethod
    def validate_properties_json(cls, v: str) -> str:
        """Ensure properties is valid JSON."""
        import json

        try:
            json.loads(v)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("properties must be a valid JSON string")
        return v

    @field_validator("object_id")
    @classmethod
    def validate_object_id_chars(cls, v: str) -> str:
        """Ensure object_id contains only safe characters for table naming."""
        sanitised = v.replace("-", "_").replace(" ", "_")
        if not sanitised.replace("_", "").isalnum():
            raise ValueError(
                "object_id must contain only alphanumeric characters, "
                "hyphens, or underscores."
            )
        return v


class TrinoInsertRequest(BaseModel):
    """Request body for ``POST /api/v1/dynamic-objects/{object_type}/data``.

    Supports both single-record and batch INSERT via Trino SQL.

    - If ``records`` contains exactly 1 element → single INSERT
    - If ``records`` contains >1 elements → batch INSERT (multi-row VALUES)

    All records in a request should belong to the same ``object_id``.
    The ``object_type`` is taken from the URL path parameter and used for
    type-aware table creation (extended schema columns for the type).
    """

    object_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=(
            "Target dynamic object ID. All records must match this ID. "
            "The per-object Iceberg table is auto-created if needed."
        ),
        examples=["worker_01", "agv-alpha"],
    )
    records: list[SensorDataPoint] = Field(
        ...,
        min_length=1,
        description="One or more sensor data records to INSERT via Trino SQL.",
    )
    chunk_size: Optional[int] = Field(
        None,
        ge=1,
        le=5000,
        description=(
            "Max rows per INSERT statement for batch chunking. "
            "Defaults to 500 if omitted. Only relevant for batches > 500 rows."
        ),
    )

    @field_validator("records")
    @classmethod
    def validate_consistent_object_id(
        cls, v: list[SensorDataPoint], info
    ) -> list[SensorDataPoint]:
        """Ensure all records reference the same object_id."""
        if not v:
            return v
        ids = {r.object_id for r in v}
        if len(ids) > 1:
            raise ValueError(
                f"All records must have the same object_id. Found: {ids}"
            )
        return v


class TrinoInsertResponse(BaseModel):
    """Response after INSERT via Trino SQL."""

    inserted: int = Field(..., description="Number of records successfully inserted")
    table: str = Field(
        ..., description="Iceberg table name used (e.g., dynamic_worker_01)"
    )
    object_id: str = Field(..., description="Dynamic object identifier")
    object_type: str = Field(..., description="Object type used for table schema")
    method: str = Field(
        ...,
        description="INSERT method: 'single' or 'batch'",
        examples=["single", "batch"],
    )
    chunk_count: Optional[int] = Field(
        None,
        description="Number of INSERT statement chunks executed (batch only)",
    )
    first_timestamp: Optional[str] = Field(
        None, description="Earliest timestamp in the batch (ISO format)"
    )
    last_timestamp: Optional[str] = Field(
        None, description="Latest timestamp in the batch (ISO format)"
    )
    message: str = "ok"
