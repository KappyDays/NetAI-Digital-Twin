"""
Unit tests for catalog_init — Iceberg table schema definitions and
catalog table creation/initialization utilities.

Tests cover:
  1. TableDef / ColumnDef data structures
  2. Trino DDL generation from TableDef
  3. PyIceberg schema generation from TableDef
  4. PyArrow schema generation from TableDef
  5. Partition spec generation
  6. Schema verification result structure
  7. Static prims canonical table definition correctness
  8. Dynamic object table template correctness
  9. make_dynamic_table_def factory
 10. describe_table documentation helper
 11. InitResult dataclass
 12. Mocked bootstrap_catalog lifecycle
 13. Schema cross-consistency (Iceberg ↔ PyArrow ↔ Trino DDL)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest
from pyiceberg.schema import Schema
from pyiceberg.types import DoubleType, StringType, TimestampType

from app.services.catalog_init import (
    DYNAMIC_OBJECT_TABLE_TEMPLATE,
    STATIC_PRIMS_TABLE,
    ColumnDef,
    FieldType,
    InitResult,
    SchemaCheckResult,
    TableDef,
    describe_table,
)


# ═══════════════════════════════════════════════════════════════════════
#  1. ColumnDef Tests
# ═══════════════════════════════════════════════════════════════════════


class TestColumnDef:
    """Test ColumnDef data structure and type mappings."""

    def test_string_column(self):
        col = ColumnDef(1, "name", FieldType.STRING, required=True)
        assert col.trino_type == "VARCHAR"
        assert col.trino_nullable == " NOT NULL"

    def test_double_column(self):
        col = ColumnDef(2, "value", FieldType.DOUBLE, required=False)
        assert col.trino_type == "DOUBLE"
        assert col.trino_nullable == ""

    def test_timestamp_column(self):
        col = ColumnDef(3, "ts", FieldType.TIMESTAMP, required=False)
        assert col.trino_type == "TIMESTAMP(6)"

    def test_long_column(self):
        col = ColumnDef(4, "count", FieldType.LONG, required=True)
        assert col.trino_type == "BIGINT"
        assert col.trino_nullable == " NOT NULL"

    def test_frozen_immutability(self):
        col = ColumnDef(1, "name", FieldType.STRING)
        with pytest.raises(AttributeError):
            col.name = "other"


# ═══════════════════════════════════════════════════════════════════════
#  2. TableDef Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTableDef:
    """Test TableDef properties and DDL generation."""

    @pytest.fixture
    def sample_table(self) -> TableDef:
        return TableDef(
            namespace="test_ns",
            table_name="test_table",
            columns=(
                ColumnDef(1, "id", FieldType.STRING, required=True),
                ColumnDef(2, "value", FieldType.DOUBLE, required=False),
                ColumnDef(3, "ts", FieldType.TIMESTAMP, required=False),
            ),
            partition_columns=("id",),
            description="Test table",
        )

    def test_fqn(self, sample_table: TableDef):
        assert sample_table.fqn == "test_ns.test_table"

    def test_trino_fqn(self, sample_table: TableDef):
        assert sample_table.trino_fqn == "polaris.test_ns.test_table"

    def test_column_names(self, sample_table: TableDef):
        assert sample_table.column_names() == ["id", "value", "ts"]

    def test_trino_ddl_contains_create(self, sample_table: TableDef):
        ddl = sample_table.to_trino_ddl()
        assert "CREATE TABLE IF NOT EXISTS" in ddl
        assert "polaris.test_ns.test_table" in ddl

    def test_trino_ddl_contains_columns(self, sample_table: TableDef):
        ddl = sample_table.to_trino_ddl()
        assert "id" in ddl
        assert "VARCHAR" in ddl
        assert "NOT NULL" in ddl
        assert "DOUBLE" in ddl
        assert "TIMESTAMP(6)" in ddl

    def test_trino_ddl_contains_partitioning(self, sample_table: TableDef):
        ddl = sample_table.to_trino_ddl()
        assert "partitioning" in ddl
        assert "'id'" in ddl
        assert "PARQUET" in ddl

    def test_trino_ddl_no_partitioning_when_empty(self):
        tbl = TableDef(
            namespace="ns",
            table_name="tbl",
            columns=(ColumnDef(1, "a", FieldType.STRING),),
            partition_columns=(),
        )
        ddl = tbl.to_trino_ddl()
        assert "partitioning" not in ddl
        assert "PARQUET" in ddl


# ═══════════════════════════════════════════════════════════════════════
#  3. PyIceberg Schema Generation
# ═══════════════════════════════════════════════════════════════════════


class TestIcebergSchemaGeneration:
    """Test TableDef -> PyIceberg Schema conversion."""

    def test_static_prims_iceberg_schema(self):
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        assert isinstance(schema, Schema)
        assert len(schema.fields) == 5

    def test_field_names_match(self):
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        names = [f.name for f in schema.fields]
        assert names == ["prim_path", "type", "properties", "space_id", "ingested_at"]

    def test_required_fields(self):
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        field_map = {f.name: f for f in schema.fields}
        assert field_map["prim_path"].required is True
        assert field_map["type"].required is True
        assert field_map["properties"].required is False
        assert field_map["space_id"].required is False
        assert field_map["ingested_at"].required is False

    def test_field_types(self):
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        field_map = {f.name: f for f in schema.fields}
        assert isinstance(field_map["prim_path"].field_type, StringType)
        assert isinstance(field_map["type"].field_type, StringType)
        assert isinstance(field_map["ingested_at"].field_type, TimestampType)

    def test_field_ids(self):
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        ids = [f.field_id for f in schema.fields]
        assert ids == [1, 2, 3, 4, 5]

    def test_dynamic_template_iceberg_schema(self):
        schema = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_iceberg_schema()
        assert len(schema.fields) == 11
        names = [f.name for f in schema.fields]
        assert "object_id" in names
        assert "timestamp" in names
        assert "pos_x" in names
        assert "speed" in names
        assert "properties" in names


# ═══════════════════════════════════════════════════════════════════════
#  4. PyArrow Schema Generation
# ═══════════════════════════════════════════════════════════════════════


class TestPyArrowSchemaGeneration:
    """Test TableDef -> PyArrow Schema conversion."""

    def test_static_prims_arrow_schema(self):
        schema = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert isinstance(schema, pa.Schema)
        assert len(schema) == 5

    def test_arrow_field_names_match(self):
        schema = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert schema.names == ["prim_path", "type", "properties", "space_id", "ingested_at"]

    def test_arrow_nullable_matches_required(self):
        schema = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert schema.field("prim_path").nullable is False
        assert schema.field("type").nullable is False
        assert schema.field("properties").nullable is True
        assert schema.field("space_id").nullable is True
        assert schema.field("ingested_at").nullable is True

    def test_arrow_types(self):
        schema = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert schema.field("prim_path").type == pa.string()
        assert schema.field("ingested_at").type == pa.timestamp("us")

    def test_dynamic_template_arrow_schema(self):
        schema = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_pyarrow_schema()
        assert len(schema) == 11
        assert schema.field("pos_x").type == pa.float64()
        assert schema.field("timestamp").nullable is False


# ═══════════════════════════════════════════════════════════════════════
#  5. Partition Spec Generation
# ═══════════════════════════════════════════════════════════════════════


class TestPartitionSpec:
    """Test TableDef -> PyIceberg PartitionSpec conversion."""

    def test_static_prims_partition_spec(self):
        spec = STATIC_PRIMS_TABLE.to_partition_spec()
        assert len(spec.fields) == 1
        pf = spec.fields[0]
        assert pf.source_id == 4  # space_id field_id
        assert pf.name == "space_id_partition"

    def test_no_partition_spec(self):
        spec = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_partition_spec()
        assert len(spec.fields) == 0

    def test_invalid_partition_column_raises(self):
        tbl = TableDef(
            namespace="ns",
            table_name="t",
            columns=(ColumnDef(1, "a", FieldType.STRING),),
            partition_columns=("nonexistent",),
        )
        with pytest.raises(ValueError, match="not found in table columns"):
            tbl.to_partition_spec()


# ═══════════════════════════════════════════════════════════════════════
#  6. SchemaCheckResult
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaCheckResult:
    """Test SchemaCheckResult data structure."""

    def test_matching_schema(self):
        r = SchemaCheckResult(
            table_fqn="iceberg.static_db.static_prims",
            matches=True,
            expected_columns=["a", "b"],
            actual_columns=["a", "b"],
            message="Schema OK",
        )
        d = r.to_dict()
        assert d["matches"] is True
        assert d["missing_columns"] == []
        assert d["extra_columns"] == []

    def test_drift_detected(self):
        r = SchemaCheckResult(
            table_fqn="iceberg.static_db.static_prims",
            matches=False,
            expected_columns=["a", "b", "c"],
            actual_columns=["a", "b", "d"],
            missing_columns=["c"],
            extra_columns=["d"],
            message="Schema drift",
        )
        d = r.to_dict()
        assert d["matches"] is False
        assert "c" in d["missing_columns"]
        assert "d" in d["extra_columns"]


# ═══════════════════════════════════════════════════════════════════════
#  7. Static Prims Canonical Definition
# ═══════════════════════════════════════════════════════════════════════


class TestStaticPrimsTableDef:
    """Verify the canonical STATIC_PRIMS_TABLE definition."""

    def test_namespace(self):
        assert STATIC_PRIMS_TABLE.namespace == "static_db"

    def test_table_name(self):
        assert STATIC_PRIMS_TABLE.table_name == "static_prims"

    def test_column_count(self):
        assert len(STATIC_PRIMS_TABLE.columns) == 5

    def test_column_names(self):
        names = STATIC_PRIMS_TABLE.column_names()
        assert names == ["prim_path", "type", "properties", "space_id", "ingested_at"]

    def test_partition_by_space_id(self):
        assert STATIC_PRIMS_TABLE.partition_columns == ("space_id",)

    def test_has_description(self):
        assert "static" in STATIC_PRIMS_TABLE.description.lower()
        assert "space" in STATIC_PRIMS_TABLE.description.lower()

    def test_prim_path_required(self):
        col = next(c for c in STATIC_PRIMS_TABLE.columns if c.name == "prim_path")
        assert col.required is True

    def test_type_required(self):
        col = next(c for c in STATIC_PRIMS_TABLE.columns if c.name == "type")
        assert col.required is True

    def test_ingested_at_optional(self):
        col = next(c for c in STATIC_PRIMS_TABLE.columns if c.name == "ingested_at")
        assert col.required is False


# ═══════════════════════════════════════════════════════════════════════
#  8. Dynamic Object Template Definition
# ═══════════════════════════════════════════════════════════════════════


class TestDynamicTableTemplate:
    """Verify DYNAMIC_OBJECT_TABLE_TEMPLATE definition."""

    def test_namespace(self):
        assert DYNAMIC_OBJECT_TABLE_TEMPLATE.namespace == "dynamic_db"

    def test_column_count(self):
        assert len(DYNAMIC_OBJECT_TABLE_TEMPLATE.columns) == 11

    def test_required_fields(self):
        required = [c.name for c in DYNAMIC_OBJECT_TABLE_TEMPLATE.columns if c.required]
        assert "object_id" in required
        assert "timestamp" in required
        assert len(required) == 2

    def test_positional_fields(self):
        names = DYNAMIC_OBJECT_TABLE_TEMPLATE.column_names()
        for field in ("pos_x", "pos_y", "pos_z", "rot_x", "rot_y", "rot_z"):
            assert field in names

    def test_no_partitions(self):
        assert DYNAMIC_OBJECT_TABLE_TEMPLATE.partition_columns == ()




# ═══════════════════════════════════════════════════════════════════════
#  10. describe_table Documentation Helper
# ═══════════════════════════════════════════════════════════════════════


class TestDescribeTable:
    """Test table documentation helper."""

    def test_describe_static(self):
        info = describe_table(STATIC_PRIMS_TABLE)
        assert info["namespace"] == "static_db"
        assert info["table_name"] == "static_prims"
        assert info["column_count"] == 5
        assert len(info["columns"]) == 5
        assert "CREATE TABLE" in info["trino_ddl"]

    def test_describe_dynamic(self):
        info = describe_table(DYNAMIC_OBJECT_TABLE_TEMPLATE)
        assert info["column_count"] == 11
        assert info["partition_columns"] == []

    def test_columns_have_descriptions(self):
        info = describe_table(STATIC_PRIMS_TABLE)
        for col in info["columns"]:
            assert "description" in col
            assert col["description"]  # non-empty

    def test_json_serializable(self):
        info = describe_table(STATIC_PRIMS_TABLE)
        # Should not raise
        serialized = json.dumps(info)
        assert "static_prims" in serialized


# ═══════════════════════════════════════════════════════════════════════
#  11. InitResult Dataclass
# ═══════════════════════════════════════════════════════════════════════


class TestInitResult:
    """Test InitResult data structure."""

    def test_success_result(self):
        r = InitResult(
            success=True,
            namespaces_created=["static_db", "dynamic_db"],
            tables_created=["iceberg.static_db.static_prims"],
            elapsed_seconds=2.5,
            timestamp="2026-01-01T00:00:00Z",
        )
        d = r.to_dict()
        assert d["success"] is True
        assert len(d["namespaces_created"]) == 2
        assert d["elapsed_seconds"] == 2.5

    def test_failed_result(self):
        r = InitResult(
            success=False,
            errors=["Trino not available"],
            timestamp="2026-01-01T00:00:00Z",
        )
        d = r.to_dict()
        assert d["success"] is False
        assert "Trino not available" in d["errors"]

    def test_json_serializable(self):
        r = InitResult(success=True, timestamp="2026-01-01T00:00:00Z")
        serialized = json.dumps(r.to_dict())
        assert "success" in serialized


# ═══════════════════════════════════════════════════════════════════════
#  12. Mocked Bootstrap Lifecycle
# ═══════════════════════════════════════════════════════════════════════


class TestBootstrapCatalog:
    """Test bootstrap_catalog with mocked Trino connections."""

    @patch("app.services.catalog_init.verify_schema_via_trino")
    @patch("app.services.catalog_init.init_table_via_trino")
    @patch("app.services.catalog_init.init_namespace_via_trino")
    def test_successful_bootstrap(self, mock_ns, mock_tbl, mock_verify):
        from app.services.catalog_init import bootstrap_catalog

        mock_ns.return_value = True
        mock_tbl.return_value = True
        mock_verify.return_value = SchemaCheckResult(
            table_fqn="iceberg.static_db.static_prims",
            matches=True,
            message="OK",
        )

        result = bootstrap_catalog(wait_for_trino=False, verify_schemas=True)
        assert result.success is True
        assert len(result.namespaces_created) == 2
        assert len(result.tables_created) == 1

    @patch("app.services.catalog_init.init_namespace_via_trino")
    def test_namespace_failure(self, mock_ns):
        from app.services.catalog_init import bootstrap_catalog

        mock_ns.return_value = False

        result = bootstrap_catalog(wait_for_trino=False, verify_schemas=False)
        assert result.success is False
        assert any("namespace" in e.lower() for e in result.errors)

    @patch("app.services.catalog_init.init_table_via_trino")
    @patch("app.services.catalog_init.init_namespace_via_trino")
    def test_table_creation_failure(self, mock_ns, mock_tbl):
        from app.services.catalog_init import bootstrap_catalog

        mock_ns.return_value = True
        mock_tbl.return_value = False

        result = bootstrap_catalog(wait_for_trino=False, verify_schemas=False)
        assert result.success is False
        assert any("table" in e.lower() for e in result.errors)


# ═══════════════════════════════════════════════════════════════════════
#  13. Schema Cross-Consistency
# ═══════════════════════════════════════════════════════════════════════


class TestSchemaCrossConsistency:
    """
    Verify that Iceberg, PyArrow, and Trino DDL schemas are consistent
    with each other for the canonical STATIC_PRIMS_TABLE.
    """

    def test_iceberg_and_arrow_field_count_match(self):
        iceberg = STATIC_PRIMS_TABLE.to_iceberg_schema()
        arrow = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert len(iceberg.fields) == len(arrow)

    def test_iceberg_and_arrow_field_names_match(self):
        iceberg = STATIC_PRIMS_TABLE.to_iceberg_schema()
        arrow = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        iceberg_names = [f.name for f in iceberg.fields]
        assert arrow.names == iceberg_names

    def test_iceberg_and_arrow_nullable_consistent(self):
        iceberg = STATIC_PRIMS_TABLE.to_iceberg_schema()
        arrow = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        for ib_field in iceberg.fields:
            pa_field = arrow.field(ib_field.name)
            if ib_field.required:
                assert pa_field.nullable is False, (
                    f"{ib_field.name}: required in Iceberg but nullable in Arrow"
                )

    def test_trino_ddl_contains_all_columns(self):
        ddl = STATIC_PRIMS_TABLE.to_trino_ddl()
        for col in STATIC_PRIMS_TABLE.columns:
            assert col.name in ddl, f"Column {col.name} missing from DDL"

    def test_partition_spec_references_valid_field(self):
        spec = STATIC_PRIMS_TABLE.to_partition_spec()
        schema = STATIC_PRIMS_TABLE.to_iceberg_schema()
        field_ids = {f.field_id for f in schema.fields}
        for pf in spec.fields:
            assert pf.source_id in field_ids, (
                f"Partition field source_id={pf.source_id} not found in schema"
            )

    def test_dynamic_iceberg_arrow_consistency(self):
        """Same cross-check for the dynamic template."""
        iceberg = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_iceberg_schema()
        arrow = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_pyarrow_schema()
        assert len(iceberg.fields) == len(arrow)
        iceberg_names = [f.name for f in iceberg.fields]
        assert arrow.names == iceberg_names

    def test_generated_schemas_match_existing_iceberg_service_schemas(self):
        """
        Verify that catalog_init definitions produce schemas equivalent
        to those already defined in iceberg_service.py.
        """
        from app.services.iceberg_service import (
            DYNAMIC_OBJECT_SCHEMA,
            PA_DYNAMIC_SCHEMA,
            PA_STATIC_SCHEMA,
            STATIC_PARTITION_SPEC,
            STATIC_PRIM_SCHEMA,
        )

        # Static schema field names
        gen_names = [f.name for f in STATIC_PRIMS_TABLE.to_iceberg_schema().fields]
        existing_names = [f.name for f in STATIC_PRIM_SCHEMA.fields]
        assert gen_names == existing_names

        # Static arrow schema names
        gen_arrow = STATIC_PRIMS_TABLE.to_pyarrow_schema()
        assert gen_arrow.names == PA_STATIC_SCHEMA.names

        # Dynamic schema field names
        gen_dyn_names = [f.name for f in DYNAMIC_OBJECT_TABLE_TEMPLATE.to_iceberg_schema().fields]
        existing_dyn_names = [f.name for f in DYNAMIC_OBJECT_SCHEMA.fields]
        assert gen_dyn_names == existing_dyn_names

        # Dynamic arrow schema names
        gen_dyn_arrow = DYNAMIC_OBJECT_TABLE_TEMPLATE.to_pyarrow_schema()
        assert gen_dyn_arrow.names == PA_DYNAMIC_SCHEMA.names

        # Partition spec field count
        gen_spec = STATIC_PRIMS_TABLE.to_partition_spec()
        assert len(gen_spec.fields) == len(STATIC_PARTITION_SPEC.fields)
        assert gen_spec.fields[0].source_id == STATIC_PARTITION_SPEC.fields[0].source_id
