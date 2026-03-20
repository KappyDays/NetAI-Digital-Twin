"""
Unit tests for dynamic_object_service.

Tests cover:
  - ID sanitization and table name generation
  - DDL generation for generic and typed objects
  - Object type registry and validation
  - FQTN construction
"""

from __future__ import annotations

import pytest

from app.services.dynamic_object_service import (
    OBJECT_TYPE_EXTRA_COLUMNS,
    SUPPORTED_OBJECT_TYPES,
    _build_create_table_ddl,
    _fqtn,
    _sanitize_id,
    _table_name,
    get_supported_object_types,
    validate_object_type,
)


# ═══════════════════════════════════════════════════════════════════════
#  ID Sanitization
# ═══════════════════════════════════════════════════════════════════════

class TestSanitizeId:
    def test_lowercase(self):
        assert _sanitize_id("Person_01") == "person_01"

    def test_hyphens_replaced(self):
        assert _sanitize_id("robot-arm-1") == "robot_arm_1"

    def test_spaces_replaced(self):
        assert _sanitize_id("my sensor") == "my_sensor"

    def test_special_chars_replaced(self):
        assert _sanitize_id("obj@#$123") == "obj___123"

    def test_already_clean(self):
        assert _sanitize_id("forklift_02") == "forklift_02"

    def test_strips_whitespace(self):
        # strip() runs first, then regex replaces non-alphanum/underscore
        assert _sanitize_id("  tag1  ") == "tag1"


# ═══════════════════════════════════════════════════════════════════════
#  Table Name Generation
# ═══════════════════════════════════════════════════════════════════════

class TestTableName:
    def test_prefix(self):
        name = _table_name("sensor_01")
        assert name.startswith("dynamic_")

    def test_combined(self):
        assert _table_name("Person-A") == "dynamic_person_a"

    def test_numeric(self):
        assert _table_name("42") == "dynamic_42"


# ═══════════════════════════════════════════════════════════════════════
#  FQTN Construction
# ═══════════════════════════════════════════════════════════════════════

class TestFQTN:
    def test_default_namespace(self):
        fqtn = _fqtn("dynamic_test")
        # Should be catalog.namespace.table
        parts = fqtn.split(".")
        assert len(parts) == 3
        assert parts[2] == "dynamic_test"

    def test_custom_namespace(self):
        fqtn = _fqtn("dynamic_test", namespace="custom_ns")
        assert ".custom_ns." in fqtn


# ═══════════════════════════════════════════════════════════════════════
#  DDL Generation
# ═══════════════════════════════════════════════════════════════════════

class TestBuildDDL:
    def test_generic_ddl_has_base_columns(self):
        ddl = _build_create_table_ddl("dynamic_test", "generic", "test_ns")
        assert "CREATE TABLE IF NOT EXISTS" in ddl
        assert "object_id" in ddl
        assert "timestamp" in ddl
        assert "pos_x" in ddl
        assert "pos_y" in ddl
        assert "pos_z" in ddl
        assert "rot_x" in ddl
        assert "speed" in ddl
        assert "space_id" in ddl
        assert "properties" in ddl
        assert "object_type" in ddl
        assert "PARQUET" in ddl

    def test_generic_ddl_no_extra_columns(self):
        ddl = _build_create_table_ddl("dynamic_test", "generic", "test_ns")
        # Should NOT have type-specific columns
        assert "tag_id" not in ddl
        assert "battery_level" not in ddl
        assert "vehicle_type" not in ddl

    def test_person_ddl_has_extra_columns(self):
        ddl = _build_create_table_ddl("dynamic_person_01", "person", "test_ns")
        assert "tag_id" in ddl
        assert "activity_state" in ddl
        assert "confidence" in ddl
        # Also has base columns
        assert "object_id" in ddl
        assert "pos_x" in ddl

    def test_robot_ddl_has_extra_columns(self):
        ddl = _build_create_table_ddl("dynamic_robot_01", "robot", "test_ns")
        assert "battery_level" in ddl
        assert "task_id" in ddl
        assert "payload_weight" in ddl
        assert "operational_state" in ddl

    def test_vehicle_ddl_has_extra_columns(self):
        ddl = _build_create_table_ddl("dynamic_vehicle_01", "vehicle", "test_ns")
        assert "vehicle_type" in ddl
        assert "heading" in ddl
        assert "acceleration" in ddl
        assert "load_status" in ddl

    def test_sensor_ddl_has_extra_columns(self):
        ddl = _build_create_table_ddl("dynamic_sensor_01", "sensor", "test_ns")
        assert "sensor_type" in ddl
        assert "reading_value" in ddl
        assert "reading_unit" in ddl
        assert "signal_strength" in ddl

    def test_unknown_type_treated_as_generic(self):
        ddl = _build_create_table_ddl("dynamic_x", "unknown_type_xyz", "test_ns")
        # No extra columns from any known type
        assert "tag_id" not in ddl
        assert "battery_level" not in ddl
        assert "object_id" in ddl  # base columns present


# ═══════════════════════════════════════════════════════════════════════
#  Object Type Registry
# ═══════════════════════════════════════════════════════════════════════

class TestObjectTypeRegistry:
    def test_generic_always_supported(self):
        assert "generic" in SUPPORTED_OBJECT_TYPES

    def test_all_extra_types_supported(self):
        for otype in OBJECT_TYPE_EXTRA_COLUMNS:
            assert otype in SUPPORTED_OBJECT_TYPES

    def test_validate_known_types(self):
        assert validate_object_type("generic") is True
        assert validate_object_type("person") is True
        assert validate_object_type("robot") is True
        assert validate_object_type("vehicle") is True
        assert validate_object_type("sensor") is True
        assert validate_object_type("asset") is True

    def test_validate_unknown_type(self):
        assert validate_object_type("unknown_xyz") is False

    def test_get_supported_types_structure(self):
        types = get_supported_object_types()
        assert "generic" in types
        assert types["generic"]["extra_columns"] == []

        assert "person" in types
        person_cols = types["person"]["extra_columns"]
        assert len(person_cols) > 0
        assert any(c["name"] == "tag_id" for c in person_cols)

    def test_extra_columns_have_name_and_type(self):
        types = get_supported_object_types()
        for type_name, type_info in types.items():
            for col in type_info["extra_columns"]:
                assert "name" in col
                assert "type" in col
