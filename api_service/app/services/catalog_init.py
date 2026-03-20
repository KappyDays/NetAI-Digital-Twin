"""
Iceberg catalog table creation and initialization utility.

Provides a unified entry-point for bootstrapping the entire Lakehouse schema:
  - Namespace creation (static_db, dynamic_db)
  - Static table (static_prims) creation with partitioning
  - Dynamic table template verification
  - Schema drift detection (compare running vs expected schema)

Can be used in two modes:
  1. Embedded — called from FastAPI lifespan (app.main)
  2. Standalone — run as ``python -m app.services.catalog_init`` for
     headless initialization (CI/CD, first-time setup)

Architecture:
  - PyIceberg path: Direct REST catalog access (Polaris) for table management
  - Trino DDL path: SQL-based table creation for cross-engine compatibility
  - Both paths produce identical Iceberg tables; the dual approach ensures
    tables are queryable from Trino and manageable via PyIceberg API.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger

# ═══════════════════════════════════════════════════════════════════════
#  Schema Definitions (single source of truth)
# ═══════════════════════════════════════════════════════════════════════

class FieldType(str, Enum):
    """Supported Iceberg/Trino column types."""
    STRING = "string"
    DOUBLE = "double"
    LONG = "long"
    TIMESTAMP = "timestamp"


@dataclass(frozen=True)
class ColumnDef:
    """Column definition for an Iceberg table."""
    field_id: int
    name: str
    field_type: FieldType
    required: bool = False
    description: str = ""

    @property
    def trino_type(self) -> str:
        """Map to Trino SQL type."""
        mapping = {
            FieldType.STRING: "VARCHAR",
            FieldType.DOUBLE: "DOUBLE",
            FieldType.LONG: "BIGINT",
            FieldType.TIMESTAMP: "TIMESTAMP(6)",
        }
        return mapping[self.field_type]

    @property
    def trino_nullable(self) -> str:
        """Return NOT NULL suffix if required."""
        return " NOT NULL" if self.required else ""


@dataclass(frozen=True)
class TableDef:
    """
    Complete Iceberg table definition.

    Serves as the single source of truth for:
      - Iceberg schema (PyIceberg NestedField list)
      - PyArrow schema (for batch writes)
      - Trino DDL (CREATE TABLE IF NOT EXISTS)
    """
    namespace: str
    table_name: str
    columns: tuple[ColumnDef, ...]
    partition_columns: tuple[str, ...] = ()
    description: str = ""

    @property
    def fqn(self) -> str:
        """Fully-qualified table name: namespace.table."""
        return f"{self.namespace}.{self.table_name}"

    @property
    def trino_fqn(self) -> str:
        """Fully-qualified name for Trino: catalog.namespace.table."""
        return f"{settings.trino_catalog}.{self.namespace}.{self.table_name}"

    def to_trino_ddl(self) -> str:
        """Generate CREATE TABLE IF NOT EXISTS DDL for Trino."""
        cols = []
        for c in self.columns:
            cols.append(f"    {c.name:<16s}{c.trino_type}{c.trino_nullable}")
        col_sql = ",\n".join(cols)

        with_clauses = ["format = 'PARQUET'"]
        if self.partition_columns:
            parts = ", ".join(f"'{p}'" for p in self.partition_columns)
            with_clauses.append(f"partitioning = ARRAY[{parts}]")
        with_sql = ",\n    ".join(with_clauses)

        return (
            f"CREATE TABLE IF NOT EXISTS {self.trino_fqn} (\n"
            f"{col_sql}\n"
            f")\n"
            f"WITH (\n"
            f"    {with_sql}\n"
            f")"
        )

    def to_iceberg_schema(self):
        """Build a PyIceberg Schema from this definition."""
        from pyiceberg.schema import Schema
        from pyiceberg.types import (
            DoubleType,
            LongType,
            NestedField,
            StringType,
            TimestampType,
        )

        type_map = {
            FieldType.STRING: StringType,
            FieldType.DOUBLE: DoubleType,
            FieldType.LONG: LongType,
            FieldType.TIMESTAMP: TimestampType,
        }

        fields = []
        for c in self.columns:
            fields.append(
                NestedField(
                    field_id=c.field_id,
                    name=c.name,
                    field_type=type_map[c.field_type](),
                    required=c.required,
                )
            )
        return Schema(*fields)

    def to_pyarrow_schema(self):
        """Build a PyArrow schema from this definition."""
        import pyarrow as pa

        type_map = {
            FieldType.STRING: pa.string(),
            FieldType.DOUBLE: pa.float64(),
            FieldType.LONG: pa.int64(),
            FieldType.TIMESTAMP: pa.timestamp("us"),
        }

        fields = []
        for c in self.columns:
            fields.append(
                pa.field(c.name, type_map[c.field_type], nullable=not c.required)
            )
        return pa.schema(fields)

    def to_partition_spec(self):
        """Build a PyIceberg PartitionSpec from partition_columns."""
        from pyiceberg.partitioning import PartitionField, PartitionSpec
        from pyiceberg.transforms import IdentityTransform

        if not self.partition_columns:
            return PartitionSpec()

        # Map partition column names to field_ids
        col_map = {c.name: c.field_id for c in self.columns}
        fields = []
        for i, col_name in enumerate(self.partition_columns):
            if col_name not in col_map:
                raise ValueError(
                    f"Partition column '{col_name}' not found in table columns"
                )
            fields.append(
                PartitionField(
                    source_id=col_map[col_name],
                    field_id=1000 + i,
                    transform=IdentityTransform(),
                    name=f"{col_name}_partition",
                )
            )
        return PartitionSpec(*fields)

    def column_names(self) -> list[str]:
        """Return ordered list of column names."""
        return [c.name for c in self.columns]


# ═══════════════════════════════════════════════════════════════════════
#  Canonical Table Definitions
# ═══════════════════════════════════════════════════════════════════════

STATIC_PRIMS_TABLE = TableDef(
    namespace="static_db",
    table_name="static_prims",
    description=(
        "Static USD Prim records — space-level storage. "
        "All child Prims under each /World/<Space> are stored here with "
        "their type, properties JSON, and auto-derived space_id. "
        "Partitioned by space_id for efficient per-space queries and overwrites."
    ),
    columns=(
        ColumnDef(1, "prim_path",   FieldType.STRING,    required=True,
                  description="Full USD Prim path (e.g. /World/Room_A/Chair_01)"),
        ColumnDef(2, "type",        FieldType.STRING,    required=True,
                  description="USD Prim type name (e.g. Xform, Mesh, Scope)"),
        ColumnDef(3, "properties",  FieldType.STRING,    required=False,
                  description="JSON string: transform, bbox, metadata, custom attrs"),
        ColumnDef(4, "space_id",    FieldType.STRING,    required=False,
                  description="Derived from /World/<SpaceName>/... path pattern"),
        ColumnDef(5, "ingested_at", FieldType.TIMESTAMP, required=False,
                  description="UTC timestamp when the record was ingested"),
    ),
    partition_columns=("space_id",),
)

DYNAMIC_OBJECT_TABLE_TEMPLATE = TableDef(
    namespace="dynamic_db",
    table_name="dynamic_{object_id}",
    description=(
        "Per-object dynamic table for IoT/tracking data. "
        "Fixed schema with positional + rotational fields, "
        "schema-evolution ready via the properties JSON column."
    ),
    columns=(
        ColumnDef(1,  "object_id",  FieldType.STRING,    required=True,
                  description="Unique dynamic object identifier"),
        ColumnDef(2,  "timestamp",  FieldType.TIMESTAMP, required=True,
                  description="Observation timestamp (microsecond precision)"),
        ColumnDef(3,  "pos_x",     FieldType.DOUBLE,    required=False,
                  description="X position in world coordinates"),
        ColumnDef(4,  "pos_y",     FieldType.DOUBLE,    required=False,
                  description="Y position in world coordinates"),
        ColumnDef(5,  "pos_z",     FieldType.DOUBLE,    required=False,
                  description="Z position in world coordinates"),
        ColumnDef(6,  "rot_x",     FieldType.DOUBLE,    required=False,
                  description="Euler rotation X (degrees)"),
        ColumnDef(7,  "rot_y",     FieldType.DOUBLE,    required=False,
                  description="Euler rotation Y (degrees)"),
        ColumnDef(8,  "rot_z",     FieldType.DOUBLE,    required=False,
                  description="Euler rotation Z (degrees)"),
        ColumnDef(9,  "speed",     FieldType.DOUBLE,    required=False,
                  description="Instantaneous speed (m/s)"),
        ColumnDef(10, "space_id",  FieldType.STRING,    required=False,
                  description="Current /World child space the object occupies"),
        ColumnDef(11, "properties", FieldType.STRING,   required=False,
                  description="Extra properties as JSON string (schema evolution)"),
    ),
    partition_columns=(),
)


def make_dynamic_table_def(object_id: str) -> TableDef:
    """
    Create a concrete TableDef for a specific dynamic object.

    Sanitizes object_id for use as a table name suffix.
    """
    safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
    return TableDef(
        namespace=DYNAMIC_OBJECT_TABLE_TEMPLATE.namespace,
        table_name=f"dynamic_{safe_id}",
        description=f"Dynamic object table for '{object_id}'",
        columns=DYNAMIC_OBJECT_TABLE_TEMPLATE.columns,
        partition_columns=DYNAMIC_OBJECT_TABLE_TEMPLATE.partition_columns,
    )


# ═══════════════════════════════════════════════════════════════════════
#  Schema Verification
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SchemaCheckResult:
    """Result of comparing an existing table's schema against expected."""
    table_fqn: str
    matches: bool
    expected_columns: list[str] = field(default_factory=list)
    actual_columns: list[str] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    type_mismatches: list[dict] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "table_fqn": self.table_fqn,
            "matches": self.matches,
            "expected_columns": self.expected_columns,
            "actual_columns": self.actual_columns,
            "missing_columns": self.missing_columns,
            "extra_columns": self.extra_columns,
            "type_mismatches": self.type_mismatches,
            "message": self.message,
        }


def verify_schema_via_trino(table_def: TableDef) -> SchemaCheckResult:
    """
    Verify that an existing Trino/Iceberg table matches the expected schema.

    Queries INFORMATION_SCHEMA.COLUMNS and compares against the TableDef.
    Returns a SchemaCheckResult with details about any drift.
    """
    from app.core.trino_config import trino_cursor

    result = SchemaCheckResult(
        table_fqn=table_def.trino_fqn,
        expected_columns=[c.name for c in table_def.columns],
    )

    try:
        with trino_cursor(schema=table_def.namespace) as cursor:
            cursor.execute(
                f"SELECT column_name, data_type, is_nullable "
                f"FROM {settings.trino_catalog}.information_schema.columns "
                f"WHERE table_schema = '{table_def.namespace}' "
                f"  AND table_name = '{table_def.table_name}' "
                f"ORDER BY ordinal_position"
            )
            rows = cursor.fetchall()

        if not rows:
            result.matches = False
            result.message = f"Table {table_def.trino_fqn} does not exist"
            return result

        result.actual_columns = [r[0] for r in rows]
        actual_map = {r[0]: {"type": r[1], "nullable": r[2]} for r in rows}

        # Check missing/extra columns
        expected_set = set(result.expected_columns)
        actual_set = set(result.actual_columns)
        result.missing_columns = sorted(expected_set - actual_set)
        result.extra_columns = sorted(actual_set - expected_set)

        # Check type mismatches for common columns
        trino_type_map = {
            FieldType.STRING: "varchar",
            FieldType.DOUBLE: "double",
            FieldType.LONG: "bigint",
            FieldType.TIMESTAMP: "timestamp(6)",
        }

        for col_def in table_def.columns:
            if col_def.name in actual_map:
                expected_type = trino_type_map.get(col_def.field_type, "")
                actual_type = actual_map[col_def.name]["type"].lower()
                if expected_type and expected_type != actual_type:
                    result.type_mismatches.append({
                        "column": col_def.name,
                        "expected": expected_type,
                        "actual": actual_type,
                    })

        result.matches = (
            not result.missing_columns
            and not result.extra_columns
            and not result.type_mismatches
        )

        if result.matches:
            result.message = f"Schema OK: {table_def.trino_fqn}"
        else:
            parts = []
            if result.missing_columns:
                parts.append(f"missing={result.missing_columns}")
            if result.extra_columns:
                parts.append(f"extra={result.extra_columns}")
            if result.type_mismatches:
                parts.append(f"type_drift={result.type_mismatches}")
            result.message = f"Schema drift: {', '.join(parts)}"

        return result

    except Exception as e:
        result.matches = False
        result.message = f"Schema verification failed: {e}"
        return result


# ═══════════════════════════════════════════════════════════════════════
#  Initialization via Trino DDL
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class InitResult:
    """Result of a catalog initialization operation."""
    success: bool
    namespaces_created: list[str] = field(default_factory=list)
    tables_created: list[str] = field(default_factory=list)
    tables_verified: list[str] = field(default_factory=list)
    schema_checks: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "namespaces_created": self.namespaces_created,
            "tables_created": self.tables_created,
            "tables_verified": self.tables_verified,
            "schema_checks": self.schema_checks,
            "errors": self.errors,
            "elapsed_seconds": self.elapsed_seconds,
            "timestamp": self.timestamp,
        }


def init_namespace_via_trino(namespace: str) -> bool:
    """Create an Iceberg namespace via Trino DDL if it doesn't exist."""
    from app.core.trino_config import trino_cursor

    catalog = settings.trino_catalog
    try:
        with trino_cursor(schema=None) as cursor:
            cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{namespace}")
            cursor.fetchall()
        logger.info("Ensured namespace: %s.%s", catalog, namespace)
        return True
    except Exception as e:
        logger.error("Failed to create namespace %s: %s", namespace, e)
        return False


def init_table_via_trino(table_def: TableDef) -> bool:
    """
    Create an Iceberg table via Trino DDL if it doesn't exist.

    Uses the TableDef to generate the CREATE TABLE DDL.
    """
    from app.core.trino_config import trino_cursor

    try:
        # Ensure namespace exists first
        init_namespace_via_trino(table_def.namespace)

        ddl = table_def.to_trino_ddl()
        with trino_cursor(schema=table_def.namespace) as cursor:
            cursor.execute(ddl)
            cursor.fetchall()

        logger.info("Ensured table: %s", table_def.trino_fqn)
        return True
    except Exception as e:
        logger.error("Failed to create table %s: %s", table_def.trino_fqn, e)
        return False


def init_table_via_pyiceberg(table_def: TableDef):
    """
    Create an Iceberg table via PyIceberg REST catalog.

    Returns the PyIceberg Table reference.
    """
    from pyiceberg.exceptions import (
        NamespaceAlreadyExistsError,
        NoSuchTableError,
    )

    from app.services.iceberg_service import get_catalog

    catalog = get_catalog()

    # Ensure namespace
    try:
        catalog.create_namespace(table_def.namespace)
        logger.info("Created namespace via PyIceberg: %s", table_def.namespace)
    except NamespaceAlreadyExistsError:
        pass

    # Load or create table
    identifier = table_def.fqn
    try:
        table = catalog.load_table(identifier)
        logger.info("Loaded existing table via PyIceberg: %s", identifier)
        return table
    except NoSuchTableError:
        schema = table_def.to_iceberg_schema()
        partition_spec = table_def.to_partition_spec()
        table = catalog.create_table(
            identifier,
            schema=schema,
            partition_spec=partition_spec,
        )
        logger.info(
            "Created table via PyIceberg: %s (partitions=%s)",
            identifier,
            table_def.partition_columns,
        )
        return table


# ═══════════════════════════════════════════════════════════════════════
#  Full Bootstrap Orchestrator
# ═══════════════════════════════════════════════════════════════════════

def bootstrap_catalog(
    wait_for_trino: bool = True,
    verify_schemas: bool = True,
    max_retries: int = 15,
) -> InitResult:
    """
    Full catalog bootstrap: create all namespaces and tables.

    Steps:
      1. Wait for Trino readiness (optional)
      2. Create static_db and dynamic_db namespaces
      3. Create static_prims table (partitioned by space_id)
      4. Verify schema matches expected definition (optional)

    Parameters
    ----------
    wait_for_trino : bool
        If True, block until Trino is ready.
    verify_schemas : bool
        If True, run schema drift checks after creation.
    max_retries : int
        Max attempts when waiting for Trino.

    Returns
    -------
    InitResult
        Detailed result of the initialization.
    """
    start = time.time()
    result = InitResult(
        success=False,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    # Step 1: Wait for Trino
    if wait_for_trino:
        from app.core.trino_config import wait_for_trino as _wait

        if not _wait(max_retries=max_retries):
            result.errors.append("Trino did not become ready")
            result.elapsed_seconds = round(time.time() - start, 2)
            return result

    # Step 2: Create namespaces
    for ns in ("static_db", "dynamic_db"):
        if init_namespace_via_trino(ns):
            result.namespaces_created.append(ns)
        else:
            result.errors.append(f"Failed to create namespace: {ns}")

    # Step 3: Create static_prims table
    if init_table_via_trino(STATIC_PRIMS_TABLE):
        result.tables_created.append(STATIC_PRIMS_TABLE.trino_fqn)
    else:
        result.errors.append(
            f"Failed to create table: {STATIC_PRIMS_TABLE.trino_fqn}"
        )

    # Step 4: Verify schemas
    if verify_schemas and not result.errors:
        check = verify_schema_via_trino(STATIC_PRIMS_TABLE)
        result.schema_checks.append(check.to_dict())
        if check.matches:
            result.tables_verified.append(STATIC_PRIMS_TABLE.trino_fqn)
        else:
            logger.warning("Schema drift detected: %s", check.message)

    result.success = len(result.errors) == 0
    result.elapsed_seconds = round(time.time() - start, 2)

    if result.success:
        logger.info(
            "Catalog bootstrap OK (%.1fs): ns=%s tables=%s",
            result.elapsed_seconds,
            result.namespaces_created,
            result.tables_created,
        )
    else:
        logger.error(
            "Catalog bootstrap FAILED (%.1fs): errors=%s",
            result.elapsed_seconds,
            result.errors,
        )

    return result


def get_catalog_status() -> dict:
    """
    Return a status snapshot of the catalog: namespaces, tables, schemas.

    Useful for the /health endpoint and debugging.
    """
    from app.core.trino_config import trino_cursor

    status: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "catalog": settings.trino_catalog,
        "namespaces": [],
        "tables": {},
    }

    try:
        with trino_cursor(schema=None) as cursor:
            cursor.execute(f"SHOW SCHEMAS FROM {settings.trino_catalog}")
            schemas = [r[0] for r in cursor.fetchall()]
            status["namespaces"] = schemas

            for ns in ("static_db", "dynamic_db"):
                if ns in schemas:
                    cursor.execute(
                        f"SHOW TABLES FROM {settings.trino_catalog}.{ns}"
                    )
                    tables = [r[0] for r in cursor.fetchall()]
                    status["tables"][ns] = tables

        # Schema check for static_prims
        if "static_db" in schemas:
            check = verify_schema_via_trino(STATIC_PRIMS_TABLE)
            status["static_prims_schema"] = check.to_dict()

    except Exception as e:
        status["error"] = str(e)

    return status


# ═══════════════════════════════════════════════════════════════════════
#  Schema Documentation Helper
# ═══════════════════════════════════════════════════════════════════════

def describe_table(table_def: TableDef) -> dict:
    """
    Return a human-readable description of a table definition.

    Suitable for API documentation, research papers, and debugging.
    """
    return {
        "namespace": table_def.namespace,
        "table_name": table_def.table_name,
        "fqn": table_def.trino_fqn,
        "description": table_def.description,
        "columns": [
            {
                "field_id": c.field_id,
                "name": c.name,
                "type": c.field_type.value,
                "trino_type": c.trino_type,
                "required": c.required,
                "description": c.description,
            }
            for c in table_def.columns
        ],
        "partition_columns": list(table_def.partition_columns),
        "column_count": len(table_def.columns),
        "trino_ddl": table_def.to_trino_ddl(),
    }
