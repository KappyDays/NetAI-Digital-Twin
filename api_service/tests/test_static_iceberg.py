"""
Unit tests for Static Prim Iceberg table schema, validation, and data logic.

Tests cover:
  1. Schema definitions (Iceberg + PyArrow field consistency)
  2. Prim path validation and space_id extraction
  3. Properties JSON validation
  4. Insert record preparation logic
  5. Space-level overwrite validation
  6. Table info and metadata retrieval
  7. PrimRecord / StaticPrimData serialisation round-trip

These tests use mocked PyIceberg catalog/table to avoid requiring
a running Lakehouse stack.
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pytest

from app.services.iceberg_service import (
    DYNAMIC_OBJECT_SCHEMA,
    PA_DYNAMIC_SCHEMA,
    PA_STATIC_SCHEMA,
    STATIC_PARTITION_SPEC,
    STATIC_PRIM_SCHEMA,
    _dynamic_table_name,
    extract_space_id,
    validate_prim_path,
    validate_properties_json,
)


# ═══════════════════════════════════════════════════════════════════════
#  1. Schema Consistency Tests
# ═══════════════════════════════════════════════════════════════════════


class TestStaticSchema:
    """Verify STATIC_PRIM_SCHEMA and PA_STATIC_SCHEMA are consistent."""

    def test_iceberg_schema_has_five_fields(self):
        """Static table must have exactly 5 fields."""
        assert len(STATIC_PRIM_SCHEMA.fields) == 5

    def test_iceberg_schema_field_names(self):
        """All expected field names are present in order."""
        names = [f.name for f in STATIC_PRIM_SCHEMA.fields]
        assert names == ["prim_path", "type", "properties", "space_id", "ingested_at"]

    def test_required_fields(self):
        """prim_path and type are required; others are optional."""
        field_map = {f.name: f for f in STATIC_PRIM_SCHEMA.fields}
        assert field_map["prim_path"].required is True
        assert field_map["type"].required is True
        assert field_map["properties"].required is False
        assert field_map["space_id"].required is False
        assert field_map["ingested_at"].required is False

    def test_pyarrow_schema_field_count(self):
        """PyArrow mirror schema must have same number of fields."""
        assert len(PA_STATIC_SCHEMA) == len(STATIC_PRIM_SCHEMA.fields)

    def test_pyarrow_schema_field_names_match(self):
        """PyArrow field names must match Iceberg field names."""
        iceberg_names = [f.name for f in STATIC_PRIM_SCHEMA.fields]
        arrow_names = PA_STATIC_SCHEMA.names
        assert arrow_names == iceberg_names

    def test_pyarrow_nullable_matches_iceberg_required(self):
        """PA nullable should be inverse of Iceberg required."""
        for iceberg_field in STATIC_PRIM_SCHEMA.fields:
            pa_field = PA_STATIC_SCHEMA.field(iceberg_field.name)
            if iceberg_field.required:
                assert pa_field.nullable is False, (
                    f"Field {iceberg_field.name} is required in Iceberg "
                    f"but nullable in PyArrow"
                )

    def test_partition_spec_targets_space_id(self):
        """Partition spec must partition by space_id (source_id=4)."""
        assert len(STATIC_PARTITION_SPEC.fields) == 1
        pf = STATIC_PARTITION_SPEC.fields[0]
        assert pf.source_id == 4  # space_id field_id
        assert pf.name == "space_id_partition"


class TestDynamicSchema:
    """Verify DYNAMIC_OBJECT_SCHEMA consistency."""

    def test_iceberg_schema_has_eleven_fields(self):
        assert len(DYNAMIC_OBJECT_SCHEMA.fields) == 11

    def test_required_dynamic_fields(self):
        field_map = {f.name: f for f in DYNAMIC_OBJECT_SCHEMA.fields}
        assert field_map["object_id"].required is True
        assert field_map["timestamp"].required is True
        assert field_map["pos_x"].required is False

    def test_pyarrow_dynamic_names_match(self):
        iceberg_names = [f.name for f in DYNAMIC_OBJECT_SCHEMA.fields]
        assert PA_DYNAMIC_SCHEMA.names == iceberg_names


# ═══════════════════════════════════════════════════════════════════════
#  2. Prim Path Validation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestValidatePrimPath:
    """Test prim_path format validation."""

    @pytest.mark.parametrize(
        "path",
        [
            "/World",
            "/World/Room_A",
            "/World/Room_A/Chair_01",
            "/World/Room_A/Chair_01/Mesh",
            "/World/Hallway_01/Light_A",
            "/Root/Something",
            "/Env",
        ],
    )
    def test_valid_paths(self, path: str):
        assert validate_prim_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "",              # empty
            "World/Room_A",  # no leading slash
            "/123_bad",      # starts with digit
            "//double",      # double slash
            "/",             # just slash
        ],
    )
    def test_invalid_paths(self, path: str):
        assert validate_prim_path(path) is False


# ═══════════════════════════════════════════════════════════════════════
#  3. Space ID Extraction Tests
# ═══════════════════════════════════════════════════════════════════════


class TestExtractSpaceId:
    """Test space_id derivation from prim_path."""

    def test_world_direct_child(self):
        assert extract_space_id("/World/Room_A") == "Room_A"

    def test_nested_prim(self):
        assert extract_space_id("/World/Room_A/Chair_01/Mesh") == "Room_A"

    def test_world_root(self):
        """Root /World has no space child."""
        assert extract_space_id("/World") == ""

    def test_non_world_root(self):
        """Paths not under /World return empty space_id."""
        assert extract_space_id("/OtherRoot/Something") == ""

    def test_deep_nesting(self):
        assert extract_space_id("/World/Lab_B/Rack_01/Shelf_02/Item_X") == "Lab_B"


# ═══════════════════════════════════════════════════════════════════════
#  4. Properties JSON Validation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestValidatePropertiesJson:
    """Test properties JSON validation and normalization."""

    def test_valid_json_object(self):
        result = validate_properties_json('{"key": "value"}')
        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    def test_empty_string_returns_empty_object(self):
        assert validate_properties_json("") == "{}"
        assert validate_properties_json("  ") == "{}"

    def test_none_returns_empty_object(self):
        assert validate_properties_json(None) == "{}"

    def test_complex_object(self):
        props = json.dumps({
            "transform": {"translate": {"x": 1, "y": 2, "z": 3}},
            "material": "wood",
            "tags": ["furniture", "static"],
        })
        result = validate_properties_json(props)
        parsed = json.loads(result)
        assert "transform" in parsed
        assert parsed["material"] == "wood"

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            validate_properties_json("{not valid json}")

    def test_non_object_json_raises(self):
        """Properties must be a JSON object (dict), not array or scalar."""
        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_properties_json("[1, 2, 3]")

        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_properties_json('"just a string"')


# ═══════════════════════════════════════════════════════════════════════
#  5. Insert Record Preparation Tests (mocked catalog)
# ═══════════════════════════════════════════════════════════════════════


class TestInsertStaticPrims:
    """Test insert_static_prims logic with mocked Iceberg catalog."""

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_basic_records(self, mock_ensure):
        """Basic insert should derive space_id and set ingested_at."""
        from app.services.iceberg_service import insert_static_prims

        mock_table = MagicMock()
        mock_ensure.return_value = mock_table

        records = [
            {"prim_path": "/World/Room_A/Chair", "type": "Mesh", "properties": "{}"},
            {"prim_path": "/World/Room_A/Table", "type": "Mesh", "properties": '{"material": "wood"}'},
            {"prim_path": "/World/Room_B/Light", "type": "DistantLight", "properties": "{}"},
        ]

        count = insert_static_prims(records)
        assert count == 3
        mock_table.append.assert_called_once()

        # Verify the PyArrow table passed to append
        call_args = mock_table.append.call_args
        arrow_table = call_args[0][0]
        assert isinstance(arrow_table, pa.Table)
        assert arrow_table.num_rows == 3
        assert "prim_path" in arrow_table.column_names
        assert "space_id" in arrow_table.column_names

        # Verify space_id derivation
        space_ids = arrow_table.column("space_id").to_pylist()
        assert space_ids == ["Room_A", "Room_A", "Room_B"]

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_empty_records(self, mock_ensure):
        """Empty record list should return 0 without touching catalog."""
        from app.services.iceberg_service import insert_static_prims

        count = insert_static_prims([])
        assert count == 0
        mock_ensure.assert_not_called()

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_validates_prim_path(self, mock_ensure):
        """Invalid prim_path should raise ValueError when validate=True."""
        from app.services.iceberg_service import insert_static_prims

        mock_ensure.return_value = MagicMock()
        records = [{"prim_path": "no_leading_slash", "type": "Mesh"}]
        with pytest.raises(ValueError, match="invalid prim_path format"):
            insert_static_prims(records, validate=True)

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_validates_empty_type(self, mock_ensure):
        """Empty type should raise ValueError when validate=True."""
        from app.services.iceberg_service import insert_static_prims

        mock_ensure.return_value = MagicMock()
        records = [{"prim_path": "/World/Room_A", "type": ""}]
        with pytest.raises(ValueError, match="type is required"):
            insert_static_prims(records, validate=True)

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_skips_validation(self, mock_ensure):
        """When validate=False, invalid paths are accepted."""
        from app.services.iceberg_service import insert_static_prims

        mock_table = MagicMock()
        mock_ensure.return_value = mock_table

        records = [{"prim_path": "bad_path", "type": "Mesh"}]
        count = insert_static_prims(records, validate=False)
        assert count == 1

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_insert_normalizes_properties(self, mock_ensure):
        """Properties JSON should be validated and normalized."""
        from app.services.iceberg_service import insert_static_prims

        mock_table = MagicMock()
        mock_ensure.return_value = mock_table

        records = [
            {"prim_path": "/World/Room_A/Chair", "type": "Mesh", "properties": '{"a":1}'},
        ]
        count = insert_static_prims(records, validate=True)
        assert count == 1

        arrow_table = mock_table.append.call_args[0][0]
        props = arrow_table.column("properties").to_pylist()
        assert json.loads(props[0]) == {"a": 1}


# ═══════════════════════════════════════════════════════════════════════
#  6. Space-level Overwrite Validation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestOverwriteSpacePrims:
    """Test space-level overwrite logic."""

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_overwrite_with_records(self, mock_ensure):
        """Overwrite should delete existing then append new records."""
        from app.services.iceberg_service import overwrite_space_prims

        mock_table = MagicMock()
        mock_ensure.return_value = mock_table

        records = [
            {"prim_path": "/World/Room_A/Chair", "type": "Mesh", "properties": "{}"},
            {"prim_path": "/World/Room_A/Table", "type": "Mesh", "properties": "{}"},
        ]

        count = overwrite_space_prims("Room_A", records)
        assert count == 2

        # Should delete first, then append
        mock_table.delete.assert_called_once_with("space_id = 'Room_A'")
        mock_table.append.assert_called_once()

        arrow_table = mock_table.append.call_args[0][0]
        assert arrow_table.num_rows == 2

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_overwrite_empty_records_deletes_only(self, mock_ensure):
        """Overwrite with empty records should only delete."""
        from app.services.iceberg_service import overwrite_space_prims

        mock_table = MagicMock()
        mock_ensure.return_value = mock_table

        count = overwrite_space_prims("Room_A", [])
        assert count == 0
        mock_table.delete.assert_called_once_with("space_id = 'Room_A'")
        mock_table.append.assert_not_called()

    def test_overwrite_empty_space_id_raises(self):
        """Empty space_id should raise ValueError."""
        from app.services.iceberg_service import overwrite_space_prims

        with pytest.raises(ValueError, match="space_id is required"):
            overwrite_space_prims("", [])

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_overwrite_cross_space_record_raises(self, mock_ensure):
        """Records belonging to a different space should raise ValueError."""
        from app.services.iceberg_service import overwrite_space_prims

        mock_ensure.return_value = MagicMock()
        records = [
            {"prim_path": "/World/Room_B/Chair", "type": "Mesh", "properties": "{}"},
        ]

        with pytest.raises(ValueError, match="belongs to space 'Room_B'"):
            overwrite_space_prims("Room_A", records)


# ═══════════════════════════════════════════════════════════════════════
#  7. Dynamic Table Name Generation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDynamicTableName:
    """Test dynamic table name generation."""

    def test_simple_id(self):
        assert _dynamic_table_name("robot01") == "dynamic_robot01"

    def test_hyphenated_id(self):
        assert _dynamic_table_name("robot-01") == "dynamic_robot_01"

    def test_space_in_id(self):
        assert _dynamic_table_name("robot 01") == "dynamic_robot_01"

    def test_uppercase_lowered(self):
        assert _dynamic_table_name("Robot_A") == "dynamic_robot_a"


# ═══════════════════════════════════════════════════════════════════════
#  8. Table Info Tests (mocked catalog)
# ═══════════════════════════════════════════════════════════════════════


class TestStaticTableInfo:
    """Test get_static_table_info metadata retrieval."""

    @patch("app.services.iceberg_service.ensure_static_table")
    def test_returns_schema_fields(self, mock_ensure):
        """Table info should include schema field definitions."""
        from app.services.iceberg_service import get_static_table_info

        mock_table = MagicMock()
        mock_table.schema.return_value = STATIC_PRIM_SCHEMA
        mock_table.spec.return_value = STATIC_PARTITION_SPEC
        mock_table.metadata.snapshots = []
        mock_table.metadata.current_snapshot_id = None
        mock_table.metadata.location = "s3://warehouse2/static_db/static_prims"
        mock_ensure.return_value = mock_table

        info = get_static_table_info()
        assert info["status"] == "ok"
        assert len(info["schema_fields"]) == 5
        field_names = [f["name"] for f in info["schema_fields"]]
        assert "prim_path" in field_names
        assert "space_id" in field_names


# ═══════════════════════════════════════════════════════════════════════
#  9. PrimRecord / StaticPrimData Round-Trip Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPrimRecordSerialization:
    """Test PrimRecord and StaticPrimData serialisation."""

    def test_prim_record_creation(self):
        from app.models.schemas import PrimRecord

        record = PrimRecord(
            prim_path="/World/Room_A/Chair_01",
            type="Mesh",
            properties='{"material": "wood"}',
        )
        assert record.prim_path == "/World/Room_A/Chair_01"
        assert record.object_type == "Mesh"

    def test_static_prim_data_space_derivation(self):
        from app.models.schemas import StaticPrimData

        prim = StaticPrimData(
            prim_path="/World/Room_A/Chair_01",
            object_type="Mesh",
        )
        assert prim.space_id == "Room_A"

    def test_static_prim_data_to_record_round_trip(self):
        from app.models.schemas import StaticPrimData, Transform, Vec3

        original = StaticPrimData(
            prim_path="/World/Room_A/Chair_01",
            object_type="Mesh",
            transform=Transform(
                translate=Vec3(x=1.0, y=2.0, z=3.0),
                rotate=Vec3(x=0.0, y=90.0, z=0.0),
            ),
            child_count=2,
        )

        # Flatten to PrimRecord
        record = original.to_prim_record()
        assert record.prim_path == "/World/Room_A/Chair_01"
        props = json.loads(record.properties)
        assert props["transform"]["translate"]["x"] == 1.0
        assert props["child_count"] == 2

        # Reconstruct from PrimRecord
        restored = StaticPrimData.from_prim_record(record, space_id="Room_A")
        assert restored.prim_path == original.prim_path
        assert restored.object_type == original.object_type
        assert restored.transform.translate.x == 1.0
        assert restored.transform.rotate.y == 90.0
        assert restored.child_count == 2


# ═══════════════════════════════════════════════════════════════════════
#  10. Ensure Static Table Tests (mocked catalog)
# ═══════════════════════════════════════════════════════════════════════


class TestEnsureStaticTable:
    """Test ensure_static_table creation/loading logic."""

    @patch("app.services.iceberg_service.get_catalog")
    @patch("app.services.iceberg_service._ensure_namespace")
    def test_loads_existing_table(self, mock_ns, mock_catalog_fn):
        """If table exists, load it without creating."""
        from app.services.iceberg_service import ensure_static_table

        mock_catalog = MagicMock()
        mock_table = MagicMock()
        mock_catalog.load_table.return_value = mock_table
        mock_catalog_fn.return_value = mock_catalog

        result = ensure_static_table(namespace="test_ns", table_name="test_tbl")
        assert result == mock_table
        mock_catalog.load_table.assert_called_once_with("test_ns.test_tbl")
        mock_catalog.create_table.assert_not_called()

    @patch("app.services.iceberg_service.get_catalog")
    @patch("app.services.iceberg_service._ensure_namespace")
    def test_creates_new_table(self, mock_ns, mock_catalog_fn):
        """If table doesn't exist, create it with schema and partition spec."""
        from pyiceberg.exceptions import NoSuchTableError

        from app.services.iceberg_service import ensure_static_table

        mock_catalog = MagicMock()
        mock_catalog.load_table.side_effect = NoSuchTableError("not found")
        mock_new_table = MagicMock()
        mock_catalog.create_table.return_value = mock_new_table
        mock_catalog_fn.return_value = mock_catalog

        result = ensure_static_table(namespace="test_ns", table_name="test_tbl")
        assert result == mock_new_table
        mock_catalog.create_table.assert_called_once()

        # Verify partition spec was passed
        call_kwargs = mock_catalog.create_table.call_args
        assert call_kwargs[1]["partition_spec"] == STATIC_PARTITION_SPEC
