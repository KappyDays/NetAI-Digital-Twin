"""
Tests for POST /api/v1/dynamic-objects/{object_type}/data endpoint.

Validates:
  - Single-record INSERT via Trino SQL
  - Batch INSERT via Trino SQL (multi-row VALUES)
  - Object-type-aware table creation (person, robot, vehicle, etc.)
  - Input validation (object_type, object_id mismatch, empty records)
  - Chunked batch INSERT for large payloads
  - Error propagation from Trino service layer

Endpoints under test:
  POST /api/v1/dynamic-objects/{object_type}/data
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def client():
    """Return a FastAPI TestClient."""
    return TestClient(app)


@pytest.fixture()
def single_record_payload() -> dict[str, Any]:
    """Single sensor data record payload for a person-type object."""
    return {
        "object_id": "worker_01",
        "records": [
            {
                "object_id": "worker_01",
                "timestamp": "2026-03-19T10:00:00",
                "pos_x": 1.5,
                "pos_y": 2.3,
                "pos_z": 0.0,
                "rot_x": 0.0,
                "rot_y": 0.0,
                "rot_z": 45.0,
                "speed": 1.2,
                "space_id": "Room_A",
                "properties": json.dumps({"tag_id": "UWB_042", "confidence": 0.95}),
            }
        ],
    }


@pytest.fixture()
def batch_record_payload() -> dict[str, Any]:
    """Batch of 5 sensor records for a robot-type object."""
    base_time = datetime(2026, 3, 19, 10, 0, 0)
    records = []
    for i in range(5):
        records.append({
            "object_id": "agv_01",
            "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
            "pos_x": 1.0 + i * 0.5,
            "pos_y": 2.0 + i * 0.3,
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": float(i * 15),
            "speed": 0.5 + i * 0.1,
            "space_id": "Warehouse",
            "properties": json.dumps({"battery": 95 - i, "task_id": f"TASK_{i:03d}"}),
        })
    return {
        "object_id": "agv_01",
        "records": records,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Test: Single Record INSERT
# ═══════════════════════════════════════════════════════════════════════

class TestSingleRecordInsert:
    """Tests for single-record INSERT via Trino SQL."""

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_single_insert_person(self, mock_ensure, mock_sds, client, single_record_payload):
        """Single record INSERT for person type returns correct response."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_worker_01"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": "dynamic_worker_01",
            "object_id": "worker_01",
        }

        resp = client.post(
            "/api/v1/dynamic-objects/person/data",
            json=single_record_payload,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 1
        assert body["table"] == "dynamic_worker_01"
        assert body["object_id"] == "worker_01"
        assert body["object_type"] == "person"
        assert body["method"] == "single"
        assert body["first_timestamp"] == "2026-03-19T10:00:00"
        assert body["last_timestamp"] == "2026-03-19T10:00:00"
        assert "Trino SQL single INSERT" in body["message"]

        # Verify ensure_typed_table was called with correct type
        mock_ensure.assert_called_once_with("worker_01", object_type="person")

        # Verify insert_single was called (not insert_batch)
        mock_sds.insert_single.assert_called_once()
        mock_sds.insert_batch.assert_not_called()

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_single_insert_generic_type(self, mock_ensure, mock_sds, client):
        """Single record INSERT for generic type works."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_sensor_x1"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": "dynamic_sensor_x1",
            "object_id": "sensor_x1",
        }

        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "sensor_x1",
                "records": [
                    {
                        "object_id": "sensor_x1",
                        "timestamp": "2026-03-19T12:00:00",
                        "pos_x": 10.5,
                        "pos_y": 20.3,
                        "pos_z": 1.0,
                        "speed": 0.0,
                        "space_id": "Server_Room",
                        "properties": '{"type": "temperature", "value": 23.5}',
                    }
                ],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == "generic"
        assert body["method"] == "single"
        assert body["inserted"] == 1

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_single_insert_no_timestamp_auto_fills(self, mock_ensure, mock_sds, client):
        """When timestamp is omitted, server still processes correctly."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_tag_001"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": "dynamic_tag_001",
            "object_id": "tag_001",
        }

        resp = client.post(
            "/api/v1/dynamic-objects/asset/data",
            json={
                "object_id": "tag_001",
                "records": [
                    {
                        "object_id": "tag_001",
                        "pos_x": 5.0,
                        "pos_y": 3.0,
                        "space_id": "Storage",
                    }
                ],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 1
        assert body["object_type"] == "asset"


# ═══════════════════════════════════════════════════════════════════════
#  Test: Batch INSERT
# ═══════════════════════════════════════════════════════════════════════

class TestBatchInsert:
    """Tests for batch INSERT via Trino SQL (multi-row VALUES)."""

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_batch_insert_robot(self, mock_ensure, mock_sds, client, batch_record_payload):
        """Batch of 5 records for robot type uses batch INSERT."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_agv_01"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_batch.return_value = {
            "inserted": 5,
            "table": "dynamic_agv_01",
            "object_id": "agv_01",
            "chunk_count": 1,
        }

        resp = client.post(
            "/api/v1/dynamic-objects/robot/data",
            json=batch_record_payload,
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 5
        assert body["table"] == "dynamic_agv_01"
        assert body["object_type"] == "robot"
        assert body["method"] == "batch"
        assert body["chunk_count"] == 1
        assert body["first_timestamp"] is not None
        assert body["last_timestamp"] is not None
        assert "batch INSERT" in body["message"]

        # Verify insert_batch was called (not insert_single)
        mock_sds.insert_batch.assert_called_once()
        mock_sds.insert_single.assert_not_called()

        # Verify chunk_size was passed
        call_kwargs = mock_sds.insert_batch.call_args
        assert call_kwargs.kwargs["chunk_size"] == 500
        assert call_kwargs.kwargs["ensure_table"] is False

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_batch_insert_custom_chunk_size(self, mock_ensure, mock_sds, client):
        """Custom chunk_size is forwarded to sensor_data_service."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_fleet_01"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_batch.return_value = {
            "inserted": 3,
            "table": "dynamic_fleet_01",
            "object_id": "fleet_01",
            "chunk_count": 1,
        }

        base_time = datetime(2026, 3, 19, 10, 0, 0)
        records = [
            {
                "object_id": "fleet_01",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "pos_x": float(i),
                "pos_y": float(i),
                "speed": 1.0,
                "space_id": "Yard",
            }
            for i in range(3)
        ]

        resp = client.post(
            "/api/v1/dynamic-objects/vehicle/data",
            json={
                "object_id": "fleet_01",
                "records": records,
                "chunk_size": 100,
            },
        )

        assert resp.status_code == 201
        # Verify custom chunk_size was used
        call_kwargs = mock_sds.insert_batch.call_args
        assert call_kwargs.kwargs["chunk_size"] == 100

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_batch_insert_large_payload(self, mock_ensure, mock_sds, client):
        """Large batch (100 records) processes correctly."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_mass_sensor"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_batch.return_value = {
            "inserted": 100,
            "table": "dynamic_mass_sensor",
            "object_id": "mass_sensor",
            "chunk_count": 1,
        }

        base_time = datetime(2026, 3, 19, 10, 0, 0)
        records = [
            {
                "object_id": "mass_sensor",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "pos_x": float(i % 10),
                "pos_y": float(i // 10),
                "speed": 0.5,
                "space_id": f"Zone_{i % 4}",
            }
            for i in range(100)
        ]

        resp = client.post(
            "/api/v1/dynamic-objects/sensor/data",
            json={
                "object_id": "mass_sensor",
                "records": records,
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 100
        assert body["object_type"] == "sensor"
        assert body["method"] == "batch"


# ═══════════════════════════════════════════════════════════════════════
#  Test: Validation Errors
# ═══════════════════════════════════════════════════════════════════════

class TestValidationErrors:
    """Tests for request validation on the new endpoint."""

    def test_unsupported_object_type_returns_400(self, client):
        """Unknown object_type in URL path returns 400."""
        resp = client.post(
            "/api/v1/dynamic-objects/unknown_type/data",
            json={
                "object_id": "test_01",
                "records": [
                    {"object_id": "test_01", "pos_x": 1.0, "pos_y": 2.0}
                ],
            },
        )
        assert resp.status_code == 400
        assert "Unsupported object_type" in resp.json()["detail"]
        assert "unknown_type" in resp.json()["detail"]

    def test_object_id_mismatch_returns_400(self, client):
        """Records with different object_id than request.object_id return 400."""
        resp = client.post(
            "/api/v1/dynamic-objects/person/data",
            json={
                "object_id": "worker_01",
                "records": [
                    {
                        "object_id": "worker_02",
                        "pos_x": 1.0,
                        "pos_y": 2.0,
                    }
                ],
            },
        )
        # Pydantic validation catches the mismatch OR endpoint catches it
        assert resp.status_code in (400, 422)

    def test_empty_records_returns_422(self, client):
        """Empty records list fails Pydantic validation (min_length=1)."""
        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "test_01",
                "records": [],
            },
        )
        assert resp.status_code == 422  # Pydantic min_length=1 validation

    def test_missing_object_id_in_record_returns_422(self, client):
        """Record without required object_id field fails validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "test_01",
                "records": [
                    {"pos_x": 1.0, "pos_y": 2.0}
                ],
            },
        )
        assert resp.status_code == 422

    def test_invalid_properties_json_returns_422(self, client):
        """Invalid JSON in properties field fails validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "test_01",
                "records": [
                    {
                        "object_id": "test_01",
                        "properties": "not valid json {{{",
                    }
                ],
            },
        )
        assert resp.status_code == 422

    def test_negative_speed_returns_422(self, client):
        """Negative speed fails ge=0.0 validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "test_01",
                "records": [
                    {
                        "object_id": "test_01",
                        "speed": -1.0,
                    }
                ],
            },
        )
        assert resp.status_code == 422

    def test_invalid_object_id_chars_returns_422(self, client):
        """Object ID with special characters fails validation."""
        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "test@#$%",
                "records": [
                    {"object_id": "test@#$%", "pos_x": 1.0}
                ],
            },
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  Test: Error Handling
# ═══════════════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Tests for error propagation and fallback logic."""

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_trino_insert_failure_returns_500(self, mock_ensure, mock_sds, client):
        """Trino INSERT failure propagates as 500."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_fail_01"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.side_effect = RuntimeError("Trino connection refused")

        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "fail_01",
                "records": [
                    {"object_id": "fail_01", "pos_x": 1.0, "pos_y": 2.0}
                ],
            },
        )

        assert resp.status_code == 500
        assert "Trino SQL INSERT failed" in resp.json()["detail"]
        assert "Trino connection refused" in resp.json()["detail"]

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_typed_table_fallback_to_base_schema(
        self, mock_typed_ensure, mock_base_init, mock_sds, client
    ):
        """When type-aware table creation fails, falls back to base DDL."""
        mock_typed_ensure.side_effect = RuntimeError("PyIceberg error")
        mock_base_init.return_value = "iceberg.static_db.dynamic_fallback_01"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": "dynamic_fallback_01",
            "object_id": "fallback_01",
        }

        resp = client.post(
            "/api/v1/dynamic-objects/robot/data",
            json={
                "object_id": "fallback_01",
                "records": [
                    {"object_id": "fallback_01", "pos_x": 1.0, "pos_y": 2.0}
                ],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 1

        # Verify fallback was used
        mock_typed_ensure.assert_called_once()
        mock_base_init.assert_called_once_with("fallback_01")

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_batch_insert_trino_failure_returns_500(self, mock_ensure, mock_sds, client):
        """Batch INSERT Trino failure propagates as 500."""
        mock_ensure.return_value = "iceberg.static_db.dynamic_batch_fail"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_batch.side_effect = RuntimeError("Query size exceeded")

        base_time = datetime(2026, 3, 19, 10, 0, 0)
        records = [
            {
                "object_id": "batch_fail",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "pos_x": float(i),
                "pos_y": float(i),
            }
            for i in range(3)
        ]

        resp = client.post(
            "/api/v1/dynamic-objects/generic/data",
            json={
                "object_id": "batch_fail",
                "records": records,
            },
        )

        assert resp.status_code == 500
        assert "Trino SQL INSERT failed" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════
#  Test: All Supported Object Types
# ═══════════════════════════════════════════════════════════════════════

class TestAllObjectTypes:
    """Ensure all supported object types are accepted by the endpoint."""

    SUPPORTED_TYPES = ["generic", "person", "robot", "vehicle", "sensor", "asset"]

    @pytest.mark.parametrize("obj_type", SUPPORTED_TYPES)
    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_supported_type_accepted(self, mock_ensure, mock_sds, client, obj_type):
        """Each supported object_type is accepted and routes correctly."""
        mock_ensure.return_value = f"iceberg.static_db.dynamic_test_{obj_type}"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": f"dynamic_test_{obj_type}",
            "object_id": f"test_{obj_type}",
        }

        resp = client.post(
            f"/api/v1/dynamic-objects/{obj_type}/data",
            json={
                "object_id": f"test_{obj_type}",
                "records": [
                    {
                        "object_id": f"test_{obj_type}",
                        "pos_x": 1.0,
                        "pos_y": 2.0,
                        "space_id": "TestRoom",
                    }
                ],
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["object_type"] == obj_type
        assert body["inserted"] == 1

        # Verify type was passed to ensure_typed_table
        mock_ensure.assert_called_once_with(f"test_{obj_type}", object_type=obj_type)


# ═══════════════════════════════════════════════════════════════════════
#  Test: E2E Flow — Single + Batch INSERT
# ═══════════════════════════════════════════════════════════════════════

class TestE2EInsertFlow:
    """End-to-end flow testing for the Trino SQL INSERT endpoint."""

    @patch("app.routers.dynamic_objects.sensor_data_service")
    @patch("app.routers.dynamic_objects.ensure_typed_table")
    def test_single_then_batch_for_same_object(self, mock_ensure, mock_sds, client):
        """
        E2E: Insert a single record, then a batch, for the same object.
        Verifies both INSERT paths work and return correct metadata.
        """
        mock_ensure.return_value = "iceberg.static_db.dynamic_e2e_worker"
        mock_sds.DEFAULT_BATCH_CHUNK_SIZE = 500

        # ── Step 1: Single INSERT ──
        mock_sds.insert_single.return_value = {
            "inserted": 1,
            "table": "dynamic_e2e_worker",
            "object_id": "e2e_worker",
        }

        resp1 = client.post(
            "/api/v1/dynamic-objects/person/data",
            json={
                "object_id": "e2e_worker",
                "records": [
                    {
                        "object_id": "e2e_worker",
                        "timestamp": "2026-03-19T10:00:00",
                        "pos_x": 1.0,
                        "pos_y": 2.0,
                        "speed": 0.5,
                        "space_id": "Room_A",
                    }
                ],
            },
        )

        assert resp1.status_code == 201
        assert resp1.json()["method"] == "single"
        assert resp1.json()["inserted"] == 1

        # ── Step 2: Batch INSERT ──
        mock_sds.insert_batch.return_value = {
            "inserted": 3,
            "table": "dynamic_e2e_worker",
            "object_id": "e2e_worker",
            "chunk_count": 1,
        }

        base_time = datetime(2026, 3, 19, 10, 1, 0)
        batch_records = [
            {
                "object_id": "e2e_worker",
                "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
                "pos_x": 2.0 + i * 0.5,
                "pos_y": 3.0 + i * 0.3,
                "speed": 0.8,
                "space_id": "Room_A",
            }
            for i in range(3)
        ]

        resp2 = client.post(
            "/api/v1/dynamic-objects/person/data",
            json={
                "object_id": "e2e_worker",
                "records": batch_records,
            },
        )

        assert resp2.status_code == 201
        body2 = resp2.json()
        assert body2["method"] == "batch"
        assert body2["inserted"] == 3
        assert body2["chunk_count"] == 1

        # Both calls should have used the same table and object_type
        assert resp1.json()["table"] == resp2.json()["table"]
        assert resp1.json()["object_type"] == resp2.json()["object_type"] == "person"
