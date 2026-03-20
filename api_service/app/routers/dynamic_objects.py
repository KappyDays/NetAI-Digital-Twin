"""
Dynamic Objects Router — Type-aware table creation and sensor data ingestion.

This module provides the core endpoints for managing dynamic objects
in the Iceberg Lakehouse:

  POST /api/v1/dynamic-objects/{object_type}          — Register object with type-specific schema
  GET  /api/v1/dynamic-objects/types                   — List supported object types
  POST /api/v1/dynamic-objects/tables                  — Create a per-object Iceberg table (generic)
  GET  /api/v1/dynamic-objects/tables                  — List all dynamic object tables
  GET  /api/v1/dynamic-objects/tables/{id}             — Get table info for a specific object
  POST /api/v1/dynamic-objects/sensor-data             — Insert sensor/IoT data records (PyIceberg)
  POST /api/v1/dynamic-objects/{object_type}/data      — Insert sensor data via Trino SQL

Architecture:
    Each dynamic object (e.g., UWB-tracked worker, AGV) gets its own Iceberg
    table named ``dynamic_<object_id>``. The object_type determines the schema:
    a fixed base schema (object_id, timestamp, pos/rot, speed, space_id, properties)
    plus type-specific extra columns (e.g., person gets tag_id, activity_state).

    Partitioning strategy: day(timestamp) + space_id
      - Enables Iceberg partition pruning for temporal and spatial queries
      - Optimizes time-range queries and per-zone congestion analysis

    Data flow: IoT Source → POST /{type} or /sensor-data → Iceberg Table
                                                              ↓
                            Trino SQL queries ← GET /api/v1/dynamic/query/*
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import (
    init_dynamic_table,
    list_dynamic_tables as trino_list_dynamic_tables,
)
from app.schemas.dynamic_objects import (
    CreateDynamicTableRequest,
    CreateDynamicTableResponse,
    DynamicTableInfo,
    RegisterDynamicObjectRequest,
    RegisterDynamicObjectResponse,
    SensorInsertRequest,
    SensorInsertResponse,
    TrinoInsertRequest,
    TrinoInsertResponse,
)
from app.services import iceberg_service
from app.services import sensor_data_service
from app.services.dynamic_object_service import (
    OBJECT_TYPE_EXTRA_COLUMNS,
    SUPPORTED_OBJECT_TYPES,
    create_dynamic_table as service_create_dynamic_table,
    ensure_dynamic_table as ensure_typed_table,
    get_supported_object_types,
)

router = APIRouter(prefix="/dynamic-objects", tags=["Dynamic Objects Management"])


# ===================================================================
#  Table Creation
# ===================================================================

@router.post(
    "/tables",
    response_model=CreateDynamicTableResponse,
    status_code=201,
    summary="Create a dynamic object Iceberg table",
    description=(
        "Explicitly create a per-object Iceberg table for a dynamic object. "
        "The table follows a fixed schema designed for schema evolution. "
        "If the table already exists, the operation is idempotent and returns "
        "created=False with the existing table info."
    ),
    responses={
        201: {"description": "Table created or already exists"},
        400: {"description": "Invalid object_id"},
        500: {"description": "Table creation failed"},
    },
)
async def create_dynamic_table(request: CreateDynamicTableRequest):
    """
    Create a per-object Iceberg table for a dynamic object.

    This endpoint is used during:
    - Extension startup: pre-provision tables for known objects
    - Deployment automation: batch table creation for all tracked entities
    - Manual registration: add a new dynamic object to the system

    The table is named ``dynamic_<sanitised_object_id>`` and uses the fixed
    IoT schema (object_id, timestamp, pos_x/y/z, rot_x/y/z, speed,
    space_id, properties).

    If the table already exists, returns ``created: false`` without error.
    """
    object_id = request.object_id

    try:
        # Check if the table already exists via Trino
        existing_tables = trino_list_dynamic_tables()
        safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
        expected_table = f"dynamic_{safe_id}"
        already_exists = expected_table in existing_tables

        # Create (or confirm) via Trino DDL — idempotent CREATE IF NOT EXISTS
        fq_name = init_dynamic_table(object_id)

        # Also ensure via PyIceberg (for catalog consistency)
        try:
            iceberg_service.ensure_dynamic_table(object_id)
        except Exception as pyiceberg_err:
            # Non-fatal: Trino DDL already succeeded
            logger.warning(
                "PyIceberg ensure_dynamic_table fallback warning for %s: %s",
                object_id,
                pyiceberg_err,
            )

        table_info = DynamicTableInfo(
            object_id=object_id,
            table_name=expected_table,
            fully_qualified=fq_name,
        )

        logger.info(
            "Dynamic table %s for object_id=%s (created=%s)",
            "confirmed" if already_exists else "created",
            object_id,
            not already_exists,
        )

        return CreateDynamicTableResponse(
            created=not already_exists,
            table=table_info,
            message=(
                f"Table '{expected_table}' already exists"
                if already_exists
                else f"Table '{expected_table}' created successfully"
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create dynamic table for object_id=%s: %s",
            object_id,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create table for object '{object_id}': {str(e)}",
        )


# ===================================================================
#  Table Discovery
# ===================================================================

@router.get(
    "/tables",
    response_model=list[DynamicTableInfo],
    summary="List all dynamic object tables",
    description="Return metadata for all dynamic_* tables in the Iceberg namespace.",
)
async def list_all_dynamic_tables():
    """
    List all registered dynamic object Iceberg tables.

    Returns the table name, fully-qualified Trino path, and column schema
    for each table. Useful for Extension UI dropdowns and dashboard discovery.
    """
    try:
        tables = trino_list_dynamic_tables()
        catalog = settings.trino_catalog
        namespace = settings.iceberg_namespace

        return [
            DynamicTableInfo(
                object_id=tbl[len("dynamic_"):],  # strip prefix
                table_name=tbl,
                fully_qualified=f"{catalog}.{namespace}.{tbl}",
            )
            for tbl in tables
        ]
    except Exception as e:
        logger.error("Failed to list dynamic tables: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/tables/{object_id}",
    response_model=DynamicTableInfo,
    summary="Get table info for a specific dynamic object",
    responses={
        200: {"description": "Table found"},
        404: {"description": "No table for this object_id"},
    },
)
async def get_dynamic_table_info(object_id: str):
    """
    Get Iceberg table metadata for a specific dynamic object.

    Returns 404 if no table has been created for the given object_id.
    """
    try:
        safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
        expected_table = f"dynamic_{safe_id}"
        existing = trino_list_dynamic_tables()

        if expected_table not in existing:
            raise HTTPException(
                status_code=404,
                detail=f"No dynamic table found for object_id='{object_id}' "
                       f"(expected table: '{expected_table}')",
            )

        catalog = settings.trino_catalog
        namespace = settings.iceberg_namespace
        return DynamicTableInfo(
            object_id=object_id,
            table_name=expected_table,
            fully_qualified=f"{catalog}.{namespace}.{expected_table}",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get table info for %s: %s", object_id, e, exc_info=True
        )
        raise HTTPException(status_code=500, detail=str(e))


# ===================================================================
#  Sensor Data Ingestion
# ===================================================================

@router.post(
    "/sensor-data",
    response_model=SensorInsertResponse,
    status_code=201,
    summary="Insert sensor/IoT data for a dynamic object",
    description=(
        "Batch-insert sensor or IoT tracking data for a dynamic object. "
        "The per-object Iceberg table is automatically created if it doesn't "
        "exist. All records in the batch must belong to the same object_id."
    ),
    responses={
        201: {"description": "Records inserted successfully"},
        400: {"description": "Validation error (empty records, ID mismatch)"},
        500: {"description": "Insertion failed"},
    },
)
async def insert_sensor_data(request: SensorInsertRequest):
    """
    Insert IoT / tracking / sensor data for a dynamic object.

    This is the primary data ingestion endpoint for the IoT → Lakehouse pipeline:
      IoT Source → POST /sensor-data → PyIceberg → Iceberg Table (Parquet on MinIO)

    Features:
    - Auto-creates the per-object Iceberg table if it doesn't exist
    - Validates all records belong to the same object_id
    - Validates the ``properties`` field is valid JSON
    - Returns timestamp range of the inserted batch for verification

    Example payload::

        {
            "object_id": "worker_01",
            "records": [
                {
                    "object_id": "worker_01",
                    "timestamp": "2026-03-19T10:00:00",
                    "pos_x": 1.5, "pos_y": 2.3, "pos_z": 0.0,
                    "speed": 1.2,
                    "space_id": "Room_A",
                    "properties": "{\\"battery\\": 85}"
                }
            ]
        }
    """
    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    # Validate all records match the declared object_id
    mismatched = [
        r.object_id
        for r in request.records
        if r.object_id != request.object_id
    ]
    if mismatched:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Record object_id mismatch: request.object_id='{request.object_id}' "
                f"but found records with object_id={set(mismatched)}"
            ),
        )

    object_id = request.object_id

    try:
        # Convert Pydantic models to dicts for the service layer
        records = [r.model_dump() for r in request.records]

        # Insert via iceberg_service (auto-creates table if needed)
        count, table_name = iceberg_service.insert_dynamic_records(
            object_id, records
        )

        # Compute timestamp range for the response
        timestamps = sorted(r.timestamp for r in request.records)
        first_ts = timestamps[0].isoformat() if timestamps else None
        last_ts = timestamps[-1].isoformat() if timestamps else None

        logger.info(
            "Sensor data inserted: object=%s count=%d table=%s [%s → %s]",
            object_id,
            count,
            table_name,
            first_ts,
            last_ts,
        )

        return SensorInsertResponse(
            inserted=count,
            table=table_name,
            object_id=object_id,
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            message=f"Inserted {count} sensor records for object '{object_id}'",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to insert sensor data for object=%s: %s",
            object_id,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to insert sensor data for '{object_id}': {str(e)}",
        )


# ===================================================================
#  Object Type Registry
# ===================================================================

@router.get(
    "/types",
    summary="List supported dynamic object types",
    description=(
        "Return all supported object types and their extended column schemas. "
        "Each type adds type-specific columns beyond the base dynamic schema."
    ),
)
async def list_object_types():
    """
    List supported dynamic object types and their extended column definitions.

    Returns a dict mapping each type name to its extra columns and description.
    The ``generic`` type always exists with no extra columns.

    Supported types: generic, person, robot, vehicle, sensor, asset.
    """
    return get_supported_object_types()


# ===================================================================
#  Dynamic Object Registration by Type (POST /{object_type})
# ===================================================================

@router.post(
    "/{object_type}",
    response_model=RegisterDynamicObjectResponse,
    status_code=201,
    summary="Register a dynamic object with type-specific Iceberg table",
    description=(
        "Create a per-object Iceberg table for a dynamic object of a specific type. "
        "The ``object_type`` path parameter determines the table schema:\n\n"
        "- **generic**: base schema only (object_id, timestamp, pos/rot, speed, space_id, properties)\n"
        "- **person**: + tag_id, activity_state, confidence\n"
        "- **robot**: + battery_level, task_id, payload_weight, operational_state\n"
        "- **vehicle**: + vehicle_type, heading, acceleration, load_status\n"
        "- **sensor**: + sensor_type, reading_value, reading_unit, signal_strength\n"
        "- **asset**: + asset_tag, zone_transition, dwell_time_seconds\n\n"
        "**Partitioning strategy**: ``day(timestamp)`` + ``space_id``\n\n"
        "- ``day(timestamp)``: daily partitions for efficient time-range queries\n"
        "- ``space_id``: spatial partitions for per-zone congestion analysis\n\n"
        "If the table already exists, the operation is idempotent."
    ),
    responses={
        201: {"description": "Object registered and table created (or already exists)"},
        400: {"description": "Invalid object_type or object_id"},
        500: {"description": "Table creation failed"},
    },
)
async def register_dynamic_object(
    object_type: str,
    request: RegisterDynamicObjectRequest,
):
    """
    Register a dynamic object by creating its type-aware Iceberg table.

    This is the primary entry point for dynamic object registration.
    The path parameter ``object_type`` selects the appropriate schema:

    - **Base columns** (all types): object_id, timestamp, pos_x/y/z,
      rot_x/y/z, speed, space_id, properties, object_type
    - **Extra columns**: type-specific columns appended to the base schema

    **Table naming**: ``dynamic_<sanitised_object_id>``

    **Partitioning**: ``ARRAY['day(timestamp)', 'space_id']``

    **Idempotent**: If the table already exists, returns ``created: false``
    without error. The existing table schema is returned for verification.

    **Example**::

        POST /api/v1/dynamic-objects/person

        {
            "object_id": "worker_01",
            "description": "UWB-tagged warehouse worker #1"
        }

    **Response** includes the full column schema, partitioning info,
    and the fully-qualified Trino table path.
    """
    # ── Validate object_type ──────────────────────────────────────────
    if object_type not in SUPPORTED_OBJECT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported object_type: '{object_type}'. "
                f"Supported types: {sorted(SUPPORTED_OBJECT_TYPES)}"
            ),
        )

    object_id = request.object_id

    try:
        # Delegate to the service layer which handles:
        #   1. Namespace creation (if needed)
        #   2. Table existence check
        #   3. DDL generation with type-specific extra columns
        #   4. DDL execution via Trino (CREATE TABLE IF NOT EXISTS)
        #   5. Table introspection (DESCRIBE) for column metadata
        result = service_create_dynamic_table(
            object_id=object_id,
            object_type=object_type,
        )

        # Build column list for the response
        schema_columns = result.get("columns", [])
        column_names = [col["column_name"] for col in schema_columns] if schema_columns else []

        # If columns couldn't be retrieved, use the known base + extra columns
        if not column_names:
            column_names = [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id",
                "properties", "object_type",
            ]
            extra_cols = OBJECT_TYPE_EXTRA_COLUMNS.get(object_type, [])
            column_names.extend(col_name for col_name, _ in extra_cols)

        table_info = DynamicTableInfo(
            object_id=object_id,
            table_name=result["table_name"],
            fully_qualified=result["fqtn"],
            object_type=object_type,
            columns=column_names,
            partitioning=["day(timestamp)", "space_id"],
        )

        was_created = result["created"]

        logger.info(
            "Dynamic object registered: object_id=%s type=%s table=%s created=%s",
            object_id,
            object_type,
            result["table_name"],
            was_created,
        )

        return RegisterDynamicObjectResponse(
            created=was_created,
            table=table_info,
            object_type=object_type,
            schema_columns=schema_columns if schema_columns else [
                {"column_name": name, "data_type": "VARCHAR"}
                for name in column_names
            ],
            partitioning=["day(timestamp)", "space_id"],
            message=(
                f"Table '{result['table_name']}' "
                f"{'created' if was_created else 'already exists'} "
                f"for object '{object_id}' (type={object_type})"
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to register dynamic object: object_id=%s type=%s: %s",
            object_id,
            object_type,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to register object '{object_id}' "
                f"(type={object_type}): {str(e)}"
            ),
        )


# ===================================================================
#  Object-Type-Aware Sensor Data INSERT (via Trino SQL)
# ===================================================================

@router.post(
    "/{object_type}/data",
    response_model=TrinoInsertResponse,
    status_code=201,
    summary="INSERT sensor data via Trino SQL for a typed dynamic object",
    description=(
        "Insert sensor/IoT data records into a per-object Iceberg table using "
        "Trino SQL INSERT statements. The ``object_type`` in the URL path "
        "determines the table schema (base + type-specific extra columns). "
        "Supports both single-record and batch INSERT. "
        "The per-object table is auto-created if it doesn't exist."
    ),
    responses={
        201: {"description": "Records inserted successfully via Trino SQL"},
        400: {
            "description": (
                "Validation error: empty records, object_id mismatch, "
                "unsupported object_type"
            )
        },
        500: {"description": "Trino INSERT execution failed"},
    },
)
async def insert_sensor_data_via_trino(
    object_type: str,
    request: TrinoInsertRequest,
):
    """
    INSERT sensor/IoT data for a dynamic object via Trino SQL.

    This endpoint uses Trino SQL ``INSERT INTO ... VALUES`` statements
    instead of the PyIceberg Arrow batch path. It is preferred when:

    - Direct SQL INSERT is needed (e.g., from external ETL pipelines)
    - Schema validation should be enforced by Trino/Iceberg at write time
    - Batch INSERT optimization via multi-row VALUES is desired

    **Path parameter:**
      - ``object_type``: One of the supported types (``generic``, ``person``,
        ``robot``, ``vehicle``, ``sensor``, ``asset``). Determines the table
        schema and any extra columns created for the object.

    **Behaviour:**
      - If ``records`` contains exactly 1 element → single-row INSERT
      - If ``records`` contains >1 elements → batch INSERT (chunked multi-row VALUES)
      - The per-object Iceberg table is auto-created (DDL via Trino) if it
        doesn't exist, using the type-appropriate schema.

    **Example payload:**

        POST /api/v1/dynamic-objects/person/data

        {
            "object_id": "worker_01",
            "records": [
                {
                    "object_id": "worker_01",
                    "timestamp": "2026-03-19T10:00:00",
                    "pos_x": 1.5, "pos_y": 2.3, "pos_z": 0.0,
                    "speed": 1.2,
                    "space_id": "Room_A",
                    "properties": "{\\"tag_id\\": \\"UWB_042\\"}"
                }
            ]
        }
    """
    # ── Validate object_type ──────────────────────────────────────────
    if object_type not in SUPPORTED_OBJECT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported object_type: '{object_type}'. "
                f"Supported types: {sorted(SUPPORTED_OBJECT_TYPES)}"
            ),
        )

    # ── Validate records are not empty ────────────────────────────────
    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    # ── Validate all records match the declared object_id ─────────────
    mismatched = [
        r.object_id
        for r in request.records
        if r.object_id != request.object_id
    ]
    if mismatched:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Record object_id mismatch: request.object_id='{request.object_id}' "
                f"but found records with object_id={set(mismatched)}"
            ),
        )

    object_id = request.object_id
    records = [r.model_dump() for r in request.records]
    chunk_size = request.chunk_size or sensor_data_service.DEFAULT_BATCH_CHUNK_SIZE

    try:
        # ── Ensure table exists with type-aware schema ────────────────
        try:
            ensure_typed_table(object_id, object_type=object_type)
        except Exception as table_err:
            logger.warning(
                "Type-aware table ensure failed for %s (type=%s), "
                "falling back to base schema: %s",
                object_id,
                object_type,
                table_err,
            )
            # Fall back to base DDL via trino_config
            init_dynamic_table(object_id)

        # ── Dispatch: single vs batch INSERT ──────────────────────────
        is_single = len(records) == 1

        if is_single:
            result = sensor_data_service.insert_single(
                records[0], ensure_table=False  # already ensured above
            )
            method = "single"
        else:
            result = sensor_data_service.insert_batch(
                object_id=object_id,
                records=records,
                chunk_size=chunk_size,
                ensure_table=False,  # already ensured above
            )
            method = "batch"

        # ── Compute timestamp range ───────────────────────────────────
        timestamps = sorted(
            r.timestamp for r in request.records if r.timestamp is not None
        )
        first_ts = timestamps[0].isoformat() if timestamps else None
        last_ts = timestamps[-1].isoformat() if timestamps else None

        inserted_count = result["inserted"]
        table_name = result["table"]

        logger.info(
            "Trino SQL INSERT: object=%s type=%s method=%s count=%d "
            "table=%s [%s → %s]",
            object_id,
            object_type,
            method,
            inserted_count,
            table_name,
            first_ts,
            last_ts,
        )

        return TrinoInsertResponse(
            inserted=inserted_count,
            table=table_name,
            object_id=object_id,
            object_type=object_type,
            method=method,
            chunk_count=result.get("chunk_count"),
            first_timestamp=first_ts,
            last_timestamp=last_ts,
            message=(
                f"Inserted {inserted_count} sensor record(s) for "
                f"'{object_id}' (type={object_type}) via Trino SQL {method} INSERT"
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Trino SQL INSERT failed: object=%s type=%s: %s",
            object_id,
            object_type,
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Trino SQL INSERT failed for '{object_id}' "
                f"(type={object_type}): {str(e)}"
            ),
        )
