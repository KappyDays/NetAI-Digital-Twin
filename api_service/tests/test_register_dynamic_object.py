"""
Tests for POST /api/v1/dynamic-objects/{object_type} endpoint.

This endpoint registers a dynamic object by creating a per-object Iceberg table
with a type-aware schema (base + type-specific extra columns) and partitioning
strategy (day(timestamp) + space_id).

Tests cover:
  - Successful registration for each supported object type
  - Schema validation (correct base + extra columns per type)
  - Partitioning strategy verification
  - Idempotent re-registration (created=False on second call)
  - Invalid object_type returns 400
  - Invalid object_id returns 422
  - Trino failure propagates as 500
  - GET /types endpoint lists all supported types
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════
#  Test: Successful registration for each supported type
# ═══════════════════════════════════════════════════════════════════════

class TestRegisterDynamicObject:
    """Tests for POST /api/v1/dynamic-objects/{object_type}."""

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_generic_object(self, mock_create, client):
        """Register a generic object creates table with base schema only."""
        mock_create.return_value = {
            "table_name": "dynamic_worker_01",
            "fqtn": "iceberg.static_db.dynamic_worker_01",
            "object_id": "worker_01",
            "object_type": "generic",
            "created": True,
            "columns": [
                {"column_name": "object_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "timestamp", "data_type": "timestamp(6)", "extra": "", "comment": ""},
                {"column_name": "pos_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "speed", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "space_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "properties", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "object_type", "data_type": "varchar", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/generic",
            json={"object_id": "worker_01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is True
        assert body["object_type"] == "generic"
        assert body["table"]["table_name"] == "dynamic_worker_01"
        assert body["table"]["object_type"] == "generic"
        assert body["partitioning"] == ["day(timestamp)", "space_id"]
        assert "object_id" in body["table"]["columns"]
        assert "timestamp" in body["table"]["columns"]

        mock_create.assert_called_once_with(
            object_id="worker_01",
            object_type="generic",
        )

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_person_object(self, mock_create, client):
        """Register a person object includes person-specific extra columns."""
        mock_create.return_value = {
            "table_name": "dynamic_person_01",
            "fqtn": "iceberg.static_db.dynamic_person_01",
            "object_id": "person_01",
            "object_type": "person",
            "created": True,
            "columns": [
                {"column_name": "object_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "timestamp", "data_type": "timestamp(6)", "extra": "", "comment": ""},
                {"column_name": "pos_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "speed", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "space_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "properties", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "object_type", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "tag_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "activity_state", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "confidence", "data_type": "double", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/person",
            json={"object_id": "person_01", "description": "Worker with UWB tag"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is True
        assert body["object_type"] == "person"

        # Verify person-specific columns are present
        col_names = body["table"]["columns"]
        assert "tag_id" in col_names
        assert "activity_state" in col_names
        assert "confidence" in col_names

        # Verify partitioning
        assert body["partitioning"] == ["day(timestamp)", "space_id"]

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_robot_object(self, mock_create, client):
        """Register a robot object includes robot-specific extra columns."""
        mock_create.return_value = {
            "table_name": "dynamic_agv_01",
            "fqtn": "iceberg.static_db.dynamic_agv_01",
            "object_id": "agv-01",
            "object_type": "robot",
            "created": True,
            "columns": [
                {"column_name": "object_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "timestamp", "data_type": "timestamp(6)", "extra": "", "comment": ""},
                {"column_name": "pos_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "pos_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_x", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_y", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "rot_z", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "speed", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "space_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "properties", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "object_type", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "battery_level", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "task_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "payload_weight", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "operational_state", "data_type": "varchar", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/robot",
            json={"object_id": "agv-01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == "robot"

        col_names = body["table"]["columns"]
        assert "battery_level" in col_names
        assert "task_id" in col_names
        assert "payload_weight" in col_names
        assert "operational_state" in col_names

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_vehicle_object(self, mock_create, client):
        """Register a vehicle object includes vehicle-specific extra columns."""
        mock_create.return_value = {
            "table_name": "dynamic_forklift_02",
            "fqtn": "iceberg.static_db.dynamic_forklift_02",
            "object_id": "forklift_02",
            "object_type": "vehicle",
            "created": True,
            "columns": [
                {"column_name": "object_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "timestamp", "data_type": "timestamp(6)", "extra": "", "comment": ""},
                {"column_name": "vehicle_type", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "heading", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "acceleration", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "load_status", "data_type": "varchar", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/vehicle",
            json={"object_id": "forklift_02"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == "vehicle"
        col_names = body["table"]["columns"]
        assert "vehicle_type" in col_names
        assert "heading" in col_names
        assert "acceleration" in col_names
        assert "load_status" in col_names

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_sensor_object(self, mock_create, client):
        """Register a sensor object includes sensor-specific extra columns."""
        mock_create.return_value = {
            "table_name": "dynamic_uwb_anchor_01",
            "fqtn": "iceberg.static_db.dynamic_uwb_anchor_01",
            "object_id": "uwb_anchor_01",
            "object_type": "sensor",
            "created": True,
            "columns": [
                {"column_name": "sensor_type", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "reading_value", "data_type": "double", "extra": "", "comment": ""},
                {"column_name": "reading_unit", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "signal_strength", "data_type": "double", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/sensor",
            json={"object_id": "uwb_anchor_01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == "sensor"

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_asset_object(self, mock_create, client):
        """Register an asset object includes asset-specific extra columns."""
        mock_create.return_value = {
            "table_name": "dynamic_pallet_a1",
            "fqtn": "iceberg.static_db.dynamic_pallet_a1",
            "object_id": "pallet_a1",
            "object_type": "asset",
            "created": True,
            "columns": [
                {"column_name": "asset_tag", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "zone_transition", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "dwell_time_seconds", "data_type": "double", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/asset",
            json={"object_id": "pallet_a1"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == "asset"


# ═══════════════════════════════════════════════════════════════════════
#  Test: Idempotent re-registration
# ═══════════════════════════════════════════════════════════════════════

class TestIdempotentRegistration:

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_re_register_returns_created_false(self, mock_create, client):
        """Re-registering an existing object returns created=False."""
        mock_create.return_value = {
            "table_name": "dynamic_worker_01",
            "fqtn": "iceberg.static_db.dynamic_worker_01",
            "object_id": "worker_01",
            "object_type": "person",
            "created": False,
            "columns": [
                {"column_name": "object_id", "data_type": "varchar", "extra": "", "comment": ""},
                {"column_name": "timestamp", "data_type": "timestamp(6)", "extra": "", "comment": ""},
            ],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/person",
            json={"object_id": "worker_01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is False
        assert "already exists" in body["message"]


# ═══════════════════════════════════════════════════════════════════════
#  Test: Partitioning Strategy
# ═══════════════════════════════════════════════════════════════════════

class TestPartitioningStrategy:

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_partitioning_is_day_timestamp_and_space_id(self, mock_create, client):
        """Verify the partitioning strategy is day(timestamp) + space_id."""
        mock_create.return_value = {
            "table_name": "dynamic_test_obj",
            "fqtn": "iceberg.static_db.dynamic_test_obj",
            "object_id": "test_obj",
            "object_type": "generic",
            "created": True,
            "columns": [],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/generic",
            json={"object_id": "test_obj"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["partitioning"] == ["day(timestamp)", "space_id"]
        assert body["table"]["partitioning"] == ["day(timestamp)", "space_id"]


# ═══════════════════════════════════════════════════════════════════════
#  Test: Error cases
# ═══════════════════════════════════════════════════════════════════════

class TestRegistrationErrors:

    def test_unsupported_object_type_returns_400(self, client):
        """Unknown object_type should return 400 with clear error message."""
        resp = client.post(
            "/api/v1/dynamic-objects/dinosaur",
            json={"object_id": "trex_01"},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert "Unsupported object_type" in body["detail"]
        assert "dinosaur" in body["detail"]
        assert "Supported types" in body["detail"]

    def test_empty_object_id_returns_422(self, client):
        """Empty object_id should fail Pydantic validation (422)."""
        resp = client.post(
            "/api/v1/dynamic-objects/person",
            json={"object_id": ""},
        )
        assert resp.status_code == 422

    def test_invalid_object_id_chars_returns_422(self, client):
        """Object ID with invalid characters should fail validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/person",
            json={"object_id": "obj@#$invalid!"},
        )
        assert resp.status_code == 422

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_trino_failure_returns_500(self, mock_create, client):
        """Trino connection failure should propagate as 500."""
        mock_create.side_effect = RuntimeError("Trino connection refused")

        resp = client.post(
            "/api/v1/dynamic-objects/generic",
            json={"object_id": "worker_01"},
        )

        assert resp.status_code == 500
        assert "Trino connection refused" in resp.json()["detail"]

    def test_missing_object_id_returns_422(self, client):
        """Request without object_id field should fail validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/person",
            json={},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  Test: Optional fields (description, metadata)
# ═══════════════════════════════════════════════════════════════════════

class TestOptionalFields:

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_with_description_and_metadata(self, mock_create, client):
        """Optional description and metadata fields are accepted."""
        mock_create.return_value = {
            "table_name": "dynamic_agv_alpha",
            "fqtn": "iceberg.static_db.dynamic_agv_alpha",
            "object_id": "agv-alpha",
            "object_type": "robot",
            "created": True,
            "columns": [],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/robot",
            json={
                "object_id": "agv-alpha",
                "description": "Autonomous guided vehicle in warehouse zone B",
                "metadata": {
                    "manufacturer": "KUKA",
                    "max_payload_kg": 500,
                    "zone": "Warehouse_B",
                },
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is True
        assert body["object_type"] == "robot"

    @patch("app.routers.dynamic_objects.service_create_dynamic_table")
    def test_register_with_hyphenated_object_id(self, mock_create, client):
        """Hyphenated object_id is accepted and sanitized for table name."""
        mock_create.return_value = {
            "table_name": "dynamic_robot_arm_01",
            "fqtn": "iceberg.static_db.dynamic_robot_arm_01",
            "object_id": "robot-arm-01",
            "object_type": "robot",
            "created": True,
            "columns": [],
        }

        resp = client.post(
            "/api/v1/dynamic-objects/robot",
            json={"object_id": "robot-arm-01"},
        )

        assert resp.status_code == 201
        assert resp.json()["table"]["table_name"] == "dynamic_robot_arm_01"


# ═══════════════════════════════════════════════════════════════════════
#  Test: GET /types endpoint
# ═══════════════════════════════════════════════════════════════════════

class TestListObjectTypes:

    def test_list_types_returns_all_supported(self, client):
        """GET /types returns all supported object types with their extra columns."""
        resp = client.get("/api/v1/dynamic-objects/types")

        assert resp.status_code == 200
        body = resp.json()

        # Must include all expected types
        assert "generic" in body
        assert "person" in body
        assert "robot" in body
        assert "vehicle" in body
        assert "sensor" in body
        assert "asset" in body

        # Generic has no extra columns
        assert body["generic"]["extra_columns"] == []

        # Person has tag_id, activity_state, confidence
        person_cols = [c["name"] for c in body["person"]["extra_columns"]]
        assert "tag_id" in person_cols
        assert "activity_state" in person_cols
        assert "confidence" in person_cols

        # Robot has battery_level, task_id, payload_weight, operational_state
        robot_cols = [c["name"] for c in body["robot"]["extra_columns"]]
        assert "battery_level" in robot_cols
        assert "task_id" in robot_cols


# ═══════════════════════════════════════════════════════════════════════
#  Test: DDL Partitioning in service layer
# ═══════════════════════════════════════════════════════════════════════

class TestDDLPartitioning:
    """Verify the DDL generated by dynamic_object_service includes partitioning."""

    def test_ddl_includes_partitioning(self):
        """The generated DDL should include partitioning by day(timestamp) and space_id."""
        from app.services.dynamic_object_service import _build_create_table_ddl

        ddl = _build_create_table_ddl("dynamic_test", "generic", "test_ns")
        assert "partitioning" in ddl
        assert "day(timestamp)" in ddl
        assert "space_id" in ddl
        assert "PARQUET" in ddl

    def test_ddl_partitioning_for_typed_table(self):
        """Type-specific DDL should also include partitioning."""
        from app.services.dynamic_object_service import _build_create_table_ddl

        ddl = _build_create_table_ddl("dynamic_person_01", "person", "test_ns")
        assert "partitioning" in ddl
        assert "day(timestamp)" in ddl
        assert "space_id" in ddl
        # Should also have person-specific columns
        assert "tag_id" in ddl
        assert "activity_state" in ddl
