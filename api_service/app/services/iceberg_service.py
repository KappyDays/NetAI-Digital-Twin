"""
Iceberg catalog + table management via PyIceberg.

Handles both:
  - Static tables  : space-level prim storage (shared schema)
  - Dynamic tables : per-object tables with fixed IoT schema

Static Prim Storage Strategy:
  - One table (`static_prims`) stores ALL static USD Prim data
  - space_id is derived from /World/<SpaceName>/... prim path pattern
  - Space = each direct child of /World in the OpenUSD stage
  - Supports full-space overwrite (replace all prims for a given space)
  - Partition by space_id for efficient per-space queries

Dynamic Object Storage Strategy:
  - One Iceberg table per dynamic object (dynamic_<object_id>)
  - Fixed schema with positional + rotational IoT data
  - Schema evolution ready (new fields can be added without breaking)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

import pyarrow as pa
from pyiceberg.catalog import load_catalog
from pyiceberg.exceptions import (
    NamespaceAlreadyExistsError,
    NoSuchNamespaceError,
    NoSuchTableError,
)
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DoubleType,
    LongType,
    NestedField,
    StringType,
    TimestampType,
)

from app.core.config import settings
from app.core.logging import logger

# ═══════════════════════════════════════════════════════════════════════
#  Iceberg Schemas
# ═══════════════════════════════════════════════════════════════════════

STATIC_PRIM_SCHEMA = Schema(
    NestedField(field_id=1, name="prim_path", field_type=StringType(), required=True),
    NestedField(field_id=2, name="type", field_type=StringType(), required=True),
    NestedField(field_id=3, name="properties", field_type=StringType(), required=False),
    NestedField(field_id=4, name="space_id", field_type=StringType(), required=False),
    NestedField(field_id=5, name="ingested_at", field_type=TimestampType(), required=False),
)

# Partition spec: partition static_prims by space_id for efficient space-level queries
STATIC_PARTITION_SPEC = PartitionSpec(
    PartitionField(
        source_id=4,  # space_id field
        field_id=1000,
        transform=IdentityTransform(),
        name="space_id_partition",
    ),
)

DYNAMIC_OBJECT_SCHEMA = Schema(
    NestedField(field_id=1, name="object_id", field_type=StringType(), required=True),
    NestedField(field_id=2, name="timestamp", field_type=TimestampType(), required=True),
    NestedField(field_id=3, name="pos_x", field_type=DoubleType(), required=False),
    NestedField(field_id=4, name="pos_y", field_type=DoubleType(), required=False),
    NestedField(field_id=5, name="pos_z", field_type=DoubleType(), required=False),
    NestedField(field_id=6, name="rot_x", field_type=DoubleType(), required=False),
    NestedField(field_id=7, name="rot_y", field_type=DoubleType(), required=False),
    NestedField(field_id=8, name="rot_z", field_type=DoubleType(), required=False),
    NestedField(field_id=9, name="speed", field_type=DoubleType(), required=False),
    NestedField(field_id=10, name="space_id", field_type=StringType(), required=False),
    NestedField(field_id=11, name="properties", field_type=StringType(), required=False),
)

# ═══════════════════════════════════════════════════════════════════════
#  PyArrow schema mirrors (for batch writes via PyIceberg)
# ═══════════════════════════════════════════════════════════════════════

PA_STATIC_SCHEMA = pa.schema([
    pa.field("prim_path", pa.string(), nullable=False),
    pa.field("type", pa.string(), nullable=False),
    pa.field("properties", pa.string()),
    pa.field("space_id", pa.string()),
    pa.field("ingested_at", pa.timestamp("us")),
])

PA_DYNAMIC_SCHEMA = pa.schema([
    pa.field("object_id", pa.string(), nullable=False),
    pa.field("timestamp", pa.timestamp("us"), nullable=False),
    pa.field("pos_x", pa.float64()),
    pa.field("pos_y", pa.float64()),
    pa.field("pos_z", pa.float64()),
    pa.field("rot_x", pa.float64()),
    pa.field("rot_y", pa.float64()),
    pa.field("rot_z", pa.float64()),
    pa.field("speed", pa.float64()),
    pa.field("space_id", pa.string()),
    pa.field("properties", pa.string()),
])


# ═══════════════════════════════════════════════════════════════════════
#  Catalog singleton
# ═══════════════════════════════════════════════════════════════════════

_catalog = None


def get_catalog():
    """Lazy-load and return the PyIceberg REST catalog instance."""
    global _catalog
    if _catalog is None:
        _catalog = load_catalog(
            "polaris",
            **{
                "type": "rest",
                "uri": settings.iceberg_catalog_uri,
                "oauth2-server-uri": f"{settings.iceberg_catalog_uri}/v1/oauth/tokens",
                "credential": settings.polaris_credential,
                "scope": settings.polaris_scope,
                "warehouse": settings.iceberg_warehouse,
                "s3.endpoint": settings.s3_endpoint,
                "s3.access-key-id": settings.aws_access_key_id,
                "s3.secret-access-key": settings.aws_secret_access_key,
                "s3.region": settings.aws_region,
                "s3.path-style-access": "true",
            },
        )
        logger.info("PyIceberg catalog loaded: %s", settings.iceberg_catalog_uri)
    return _catalog


def reset_catalog():
    """Reset the catalog singleton (for testing or reconnection)."""
    global _catalog
    _catalog = None
    logger.info("PyIceberg catalog singleton reset")


def _ensure_namespace(namespace: str) -> None:
    """Create namespace if it doesn't exist."""
    catalog = get_catalog()
    try:
        catalog.create_namespace(namespace)
        logger.info("Created namespace: %s", namespace)
    except NamespaceAlreadyExistsError:
        pass


# ═══════════════════════════════════════════════════════════════════════
#  Validation Helpers
# ═══════════════════════════════════════════════════════════════════════

# Pattern for valid USD Prim paths: /Word/SpaceName/... or /World
_PRIM_PATH_PATTERN = re.compile(r"^/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_.]*)*$")


def validate_prim_path(prim_path: str) -> bool:
    """
    Validate that a prim_path conforms to expected USD path format.

    Valid examples:
        /World
        /World/Room_A
        /World/Room_A/Chair_01
        /World/Room_A/Chair_01/Mesh

    Invalid examples:
        World/Room_A      (no leading /)
        /World//Room_A    (double slash)
        /123_invalid      (starts with number)
    """
    if not prim_path:
        return False
    return bool(_PRIM_PATH_PATTERN.match(prim_path))


def extract_space_id(prim_path: str) -> str:
    """
    Derive space_id from a USD Prim path.

    Space = direct child of /World.
    /World/<SpaceName>/...  →  space_id = SpaceName
    /World                  →  space_id = "" (root, no space)
    /OtherRoot/...          →  space_id = "" (not under /World)

    Returns:
        The space_id string (may be empty if not under /World/<child>).
    """
    parts = prim_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "World":
        return parts[1]
    return ""


def validate_properties_json(properties: str) -> str:
    """
    Validate and normalize a properties JSON string.

    Returns the validated JSON string. Raises ValueError if invalid.
    """
    if not properties or properties.strip() == "":
        return "{}"
    try:
        parsed = json.loads(properties)
        if not isinstance(parsed, dict):
            raise ValueError(
                f"Properties must be a JSON object (dict), got {type(parsed).__name__}"
            )
        # Re-serialize to ensure consistent formatting
        return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in properties: {e}") from e


# ═══════════════════════════════════════════════════════════════════════
#  Static Prim Operations
# ═══════════════════════════════════════════════════════════════════════

def ensure_static_table(
    namespace: Optional[str] = None,
    table_name: Optional[str] = None,
) -> Table:
    """
    Create the static_prims Iceberg table if it doesn't exist; return table ref.

    The table is partitioned by space_id for efficient per-space queries
    and overwrites. Schema follows the STATIC_PRIM_SCHEMA definition.

    Parameters
    ----------
    namespace : str, optional
        Iceberg namespace (default: settings.iceberg_namespace → 'static_db').
    table_name : str, optional
        Table name (default: settings.iceberg_table_name → 'static_prims').

    Returns
    -------
    pyiceberg.table.Table
        Reference to the (possibly newly created) Iceberg table.
    """
    ns = namespace or settings.iceberg_namespace
    tbl = table_name or settings.iceberg_table_name
    _ensure_namespace(ns)
    catalog = get_catalog()
    identifier = f"{ns}.{tbl}"
    try:
        table = catalog.load_table(identifier)
        logger.debug("Loaded existing static table: %s", identifier)
        return table
    except NoSuchTableError:
        logger.info("Creating static table: %s (partitioned by space_id)", identifier)
        return catalog.create_table(
            identifier,
            schema=STATIC_PRIM_SCHEMA,
            partition_spec=STATIC_PARTITION_SPEC,
        )


def get_static_table_info(
    namespace: Optional[str] = None,
    table_name: Optional[str] = None,
) -> dict:
    """
    Return metadata about the static_prims Iceberg table.

    Includes: identifier, schema fields, partition spec, snapshot count,
    and current row count (if available).

    Returns
    -------
    dict
        Table metadata dictionary suitable for API responses.
    """
    ns = namespace or settings.iceberg_namespace
    tbl = table_name or settings.iceberg_table_name
    identifier = f"{ns}.{tbl}"

    try:
        table = ensure_static_table(namespace=ns, table_name=tbl)
        schema_fields = [
            {
                "field_id": field.field_id,
                "name": field.name,
                "type": str(field.field_type),
                "required": field.required,
            }
            for field in table.schema().fields
        ]

        snapshot_count = len(table.metadata.snapshots) if table.metadata.snapshots else 0
        current_snapshot = table.metadata.current_snapshot_id

        return {
            "status": "ok",
            "identifier": identifier,
            "schema_fields": schema_fields,
            "partition_spec": str(table.spec()),
            "snapshot_count": snapshot_count,
            "current_snapshot_id": current_snapshot,
            "location": table.metadata.location,
        }
    except Exception as e:
        logger.error("Failed to get static table info: %s", e)
        return {
            "status": "error",
            "identifier": identifier,
            "message": str(e),
        }


def insert_static_prims(records: list[dict], validate: bool = True) -> int:
    """
    Insert a batch of static Prim records into the Iceberg table.

    Each record must contain:
        - prim_path (str): Full USD Prim path (e.g., /World/Room_A/Chair_01)
        - type (str): USD Prim type name (e.g., Xform, Mesh, Scope)
        - properties (str, optional): JSON string with attributes/metadata

    The space_id is auto-derived from /World/<SpaceName>/... path pattern.
    The ingested_at timestamp is set to the current UTC time.

    Parameters
    ----------
    records : list[dict]
        List of prim record dicts with prim_path, type, and optional properties.
    validate : bool
        If True, validate prim_path format and properties JSON (default True).

    Returns
    -------
    int
        Number of records successfully inserted.

    Raises
    ------
    ValueError
        If validation is enabled and a record has invalid data.
    """
    if not records:
        return 0

    table = ensure_static_table()
    now = datetime.now(timezone.utc)

    rows: dict[str, list] = {
        "prim_path": [],
        "type": [],
        "properties": [],
        "space_id": [],
        "ingested_at": [],
    }

    for i, r in enumerate(records):
        prim_path = r.get("prim_path", "")
        prim_type = r.get("type", "")

        # Validation
        if validate:
            if not prim_path:
                raise ValueError(f"Record {i}: prim_path is required")
            if not prim_type:
                raise ValueError(f"Record {i}: type is required")
            if not validate_prim_path(prim_path):
                raise ValueError(
                    f"Record {i}: invalid prim_path format: '{prim_path}'. "
                    "Expected /World/... or similar USD path."
                )

        # Derive space_id
        space_id = extract_space_id(prim_path)

        # Validate and normalize properties JSON
        raw_props = r.get("properties", "{}")
        if validate:
            props = validate_properties_json(raw_props)
        else:
            props = raw_props if raw_props else "{}"

        rows["prim_path"].append(prim_path)
        rows["type"].append(prim_type)
        rows["properties"].append(props)
        rows["space_id"].append(space_id)
        rows["ingested_at"].append(now)

    arrow_table = pa.table(rows, schema=PA_STATIC_SCHEMA)
    table.append(arrow_table)
    logger.info(
        "Inserted %d static prim records (spaces: %s)",
        len(records),
        sorted(set(rows["space_id"])),
    )
    return len(records)


def overwrite_space_prims(space_id: str, records: list[dict]) -> int:
    """
    Replace ALL static Prim records for a given space_id.

    This performs a full overwrite of the space's data — useful when
    Isaac Sim re-exports all prims for a space (e.g., after scene edit).

    Strategy:
        1. Build new data as a PyArrow table
        2. Use Iceberg overwrite with a row-level filter on space_id
        3. Append the new records

    Parameters
    ----------
    space_id : str
        The space identifier (e.g., "Room_A").
    records : list[dict]
        New prim records for this space. Each must have prim_path, type.

    Returns
    -------
    int
        Number of records inserted after overwrite.

    Raises
    ------
    ValueError
        If space_id is empty or records contain prims from other spaces.
    """
    if not space_id:
        raise ValueError("space_id is required for space-level overwrite")
    if not records:
        # Delete all prims for this space (overwrite with empty set)
        table = ensure_static_table()
        table.delete(f"space_id = '{space_id}'")
        logger.info("Deleted all prims for space '%s' (overwrite with empty)", space_id)
        return 0

    table = ensure_static_table()
    now = datetime.now(timezone.utc)

    rows: dict[str, list] = {
        "prim_path": [],
        "type": [],
        "properties": [],
        "space_id": [],
        "ingested_at": [],
    }

    for r in records:
        prim_path = r.get("prim_path", "")
        derived_space = extract_space_id(prim_path)

        # Ensure all records belong to the target space
        if derived_space and derived_space != space_id:
            raise ValueError(
                f"Record prim_path='{prim_path}' belongs to space '{derived_space}', "
                f"but overwrite targets space '{space_id}'"
            )

        raw_props = r.get("properties", "{}")
        props = validate_properties_json(raw_props)

        rows["prim_path"].append(prim_path)
        rows["type"].append(r.get("type", ""))
        rows["properties"].append(props)
        rows["space_id"].append(space_id)
        rows["ingested_at"].append(now)

    # Step 1: Delete existing records for this space
    table.delete(f"space_id = '{space_id}'")
    logger.info("Deleted existing prims for space '%s'", space_id)

    # Step 2: Append new records
    arrow_table = pa.table(rows, schema=PA_STATIC_SCHEMA)
    table.append(arrow_table)
    logger.info(
        "Overwrote space '%s' with %d prim records",
        space_id, len(records),
    )
    return len(records)


def delete_space_prims(space_id: str) -> bool:
    """
    Delete ALL static Prim records for a given space_id.

    Parameters
    ----------
    space_id : str
        The space identifier to remove.

    Returns
    -------
    bool
        True if deletion was successful.
    """
    if not space_id:
        raise ValueError("space_id is required for deletion")

    table = ensure_static_table()
    table.delete(f"space_id = '{space_id}'")
    logger.info("Deleted all prims for space '%s'", space_id)
    return True


def scan_static_prims(
    space_id: Optional[str] = None,
    prim_type: Optional[str] = None,
    limit: int = 10000,
) -> list[dict]:
    """
    Read static prim records directly from Iceberg (PyIceberg scan).

    This bypasses Trino and reads directly from the Parquet data files.
    Useful for:
      - Quick data validation without Trino
      - Integration tests
      - Low-latency reads when Trino is unavailable

    Parameters
    ----------
    space_id : str, optional
        Filter by space_id.
    prim_type : str, optional
        Filter by prim type.
    limit : int
        Maximum rows to return.

    Returns
    -------
    list[dict]
        List of prim records as dictionaries.
    """
    table = ensure_static_table()

    # Build row filter expression
    from pyiceberg.expressions import And, EqualTo

    filters = []
    if space_id:
        filters.append(EqualTo("space_id", space_id))
    if prim_type:
        filters.append(EqualTo("type", prim_type))

    scan = table.scan(limit=limit)
    if filters:
        combined = filters[0]
        for f in filters[1:]:
            combined = And(combined, f)
        scan = table.scan(row_filter=combined, limit=limit)

    arrow_table = scan.to_arrow()
    return arrow_table.to_pylist()


# ═══════════════════════════════════════════════════════════════════════
#  Dynamic Object Operations
# ═══════════════════════════════════════════════════════════════════════

def _dynamic_table_name(object_id: str) -> str:
    """Generate a table name for a dynamic object: dynamic_<object_id>."""
    safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
    return f"dynamic_{safe_id}"


def ensure_dynamic_table(object_id: str, namespace: Optional[str] = None):
    """Create a per-object dynamic table if it doesn't exist; return table ref."""
    ns = namespace or settings.iceberg_namespace
    _ensure_namespace(ns)
    catalog = get_catalog()
    tbl_name = _dynamic_table_name(object_id)
    identifier = f"{ns}.{tbl_name}"
    try:
        return catalog.load_table(identifier), tbl_name
    except NoSuchTableError:
        logger.info("Creating dynamic table: %s", identifier)
        return catalog.create_table(identifier, schema=DYNAMIC_OBJECT_SCHEMA), tbl_name


def insert_dynamic_records(object_id: str, records: list[dict]) -> tuple[int, str]:
    """Insert IoT/tracking records for a dynamic object. Returns (count, table_name)."""
    table, tbl_name = ensure_dynamic_table(object_id)

    rows = {col: [] for col in PA_DYNAMIC_SCHEMA.names}
    for r in records:
        rows["object_id"].append(r.get("object_id", object_id))
        rows["timestamp"].append(r.get("timestamp", datetime.now(timezone.utc)))
        rows["pos_x"].append(float(r.get("pos_x", 0.0)))
        rows["pos_y"].append(float(r.get("pos_y", 0.0)))
        rows["pos_z"].append(float(r.get("pos_z", 0.0)))
        rows["rot_x"].append(float(r.get("rot_x", 0.0)))
        rows["rot_y"].append(float(r.get("rot_y", 0.0)))
        rows["rot_z"].append(float(r.get("rot_z", 0.0)))
        rows["speed"].append(float(r.get("speed", 0.0)))
        rows["space_id"].append(r.get("space_id", ""))
        rows["properties"].append(r.get("properties", "{}"))

    arrow_table = pa.table(rows, schema=PA_DYNAMIC_SCHEMA)
    table.append(arrow_table)
    logger.info("Inserted %d dynamic records for object=%s table=%s", len(records), object_id, tbl_name)
    return len(records), tbl_name
