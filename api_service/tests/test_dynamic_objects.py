"""
E2E integration tests for Dynamic object API endpoints.

Test flow:
  1. Table creation via dynamic ingest endpoint (auto-creates per-object table)
  2. Sensor/IoT data INSERT with multiple records
  3. Trino query verification via various query endpoints
  4. Multi-object scenarios (space queries, spatial range, congestion)

These tests mock the Trino and Iceberg service layers to run without
a live infrastructure stack, while verifying the full request→response
contract of every dynamic endpoint.

Endpoints under test (all under /api/v1/dynamic):
  POST /ingest                       — Ingest IoT records (auto-creates table)
  GET  /objects                      — List registered dynamic objects
  GET  /tables                       — List dynamic table names
  POST /query/time-range             — Time-windowed queries
  POST /query/by-space               — Space/zone filter queries
  GET  /query/latest                 — Latest state per object
  POST /query/trajectory             — Movement trajectory queries
  POST /query/spatial-range          — Bounding-box spatial queries
  POST /query/congestion-timeseries  — Congestion time-series aggregation
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def client():
    """Return a FastAPI TestClient for integration tests."""
    return TestClient(app)


@pytest.fixture()
def sample_records() -> list[dict[str, Any]]:
    """Generate 5 sample IoT sensor records for robot_01."""
    base_time = datetime(2026, 3, 19, 10, 0, 0)
    records = []
    for i in range(5):
        records.append({
            "object_id": "robot_01",
            "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
            "pos_x": 1.0 + i * 0.5,
            "pos_y": 2.0 + i * 0.3,
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": float(i * 15),
            "speed": 0.5 + i * 0.1,
            "space_id": "Room_A",
            "properties": json.dumps({"battery": 95 - i, "sensor": "lidar"}),
        })
    return records


@pytest.fixture()
def multi_space_records() -> list[dict[str, Any]]:
    """Generate records across multiple spaces for congestion tests."""
    base_time = datetime(2026, 3, 19, 10, 0, 0)
    records = []
    spaces = ["Room_A", "Room_B", "Room_A", "Hallway_01", "Room_B"]
    for i, space in enumerate(spaces):
        records.append({
            "object_id": f"worker_{i:02d}",
            "timestamp": (base_time + timedelta(seconds=i * 5)).isoformat(),
            "pos_x": float(i * 2),
            "pos_y": float(i * 3),
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": 0.0,
            "speed": 1.0,
            "space_id": space,
            "properties": "{}",
        })
    return records


# ═══════════════════════════════════════════════════════════════════════
#  Test 1: Ingest → Table Auto-Creation + Data Insert
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicIngest:
    """Tests for POST /api/v1/dynamic/ingest."""

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_creates_table_and_inserts(self, mock_iceberg, client, sample_records):
        """E2E: POST /ingest auto-creates table and returns correct count."""
        mock_iceberg.insert_dynamic_records.return_value = (5, "dynamic_robot_01")

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": sample_records},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["inserted"] == 5
        assert body["table"] == "dynamic_robot_01"
        assert body["object_id"] == "robot_01"
        assert "Inserted 5 records" in body["message"]

        # Verify service was called with correct object_id and record count
        mock_iceberg.insert_dynamic_records.assert_called_once()
        call_args = mock_iceberg.insert_dynamic_records.call_args
        assert call_args[0][0] == "robot_01"
        assert len(call_args[0][1]) == 5

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_single_record(self, mock_iceberg, client):
        """Ingest a single sensor data point."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_sensor_x1")

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={
                "records": [{
                    "object_id": "sensor_x1",
                    "timestamp": "2026-03-19T12:00:00",
                    "pos_x": 10.5,
                    "pos_y": 20.3,
                    "pos_z": 1.0,
                    "rot_x": 0.0,
                    "rot_y": 0.0,
                    "rot_z": 90.0,
                    "speed": 0.0,
                    "space_id": "Server_Room",
                    "properties": '{"type": "temperature", "value": 23.5}',
                }],
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["inserted"] == 1
        assert body["object_id"] == "sensor_x1"

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_empty_records_returns_400(self, mock_iceberg, client):
        """Empty records list should return 400."""
        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": []},
        )
        assert resp.status_code == 400
        assert "No records" in resp.json()["detail"]

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_service_error_returns_500(self, mock_iceberg, client, sample_records):
        """Iceberg service failure should propagate as 500."""
        mock_iceberg.insert_dynamic_records.side_effect = RuntimeError(
            "Trino connection refused"
        )

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": sample_records},
        )
        assert resp.status_code == 500
        assert "Trino connection refused" in resp.json()["detail"]

    def test_ingest_missing_required_field(self, client):
        """Records missing object_id should fail validation."""
        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={
                "records": [{
                    "timestamp": "2026-03-19T12:00:00",
                    "pos_x": 1.0,
                    "pos_y": 2.0,
                }],
            },
        )
        assert resp.status_code == 422  # Pydantic validation error


# ═══════════════════════════════════════════════════════════════════════
#  Test 2: Discovery — List Objects & Tables
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicDiscovery:
    """Tests for GET /api/v1/dynamic/objects and /tables."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_list_objects(self, mock_trino, client):
        """GET /objects returns object metadata list."""
        mock_trino.list_dynamic_objects.return_value = [
            {
                "object_id": "robot_01",
                "table_name": "dynamic_robot_01",
                "record_count": 100,
                "first_seen": "2026-03-19T10:00:00",
                "last_seen": "2026-03-19T10:16:40",
            },
            {
                "object_id": "worker_02",
                "table_name": "dynamic_worker_02",
                "record_count": 50,
                "first_seen": "2026-03-19T10:05:00",
                "last_seen": "2026-03-19T10:10:00",
            },
        ]

        resp = client.get("/api/v1/dynamic/objects")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["objects"]) == 2
        assert body["objects"][0]["object_id"] == "robot_01"
        assert body["objects"][0]["record_count"] == 100
        assert body["objects"][1]["object_id"] == "worker_02"

    @patch("app.api.v1.dynamic.trino_service")
    def test_list_objects_empty(self, mock_trino, client):
        """GET /objects returns empty list when no dynamic tables exist."""
        mock_trino.list_dynamic_objects.return_value = []

        resp = client.get("/api/v1/dynamic/objects")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["objects"] == []

    @patch("app.api.v1.dynamic.trino_service")
    def test_list_tables(self, mock_trino, client):
        """GET /tables returns dynamic table names."""
        mock_trino.list_dynamic_tables.return_value = [
            "dynamic_robot_01",
            "dynamic_worker_02",
            "dynamic_sensor_x1",
        ]

        resp = client.get("/api/v1/dynamic/tables")
        assert resp.status_code == 200
        tables = resp.json()
        assert len(tables) == 3
        assert "dynamic_robot_01" in tables


# ═══════════════════════════════════════════════════════════════════════
#  Test 3: Time-Range Query
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicTimeRangeQuery:
    """Tests for POST /api/v1/dynamic/query/time-range."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_time_range_returns_matching_rows(self, mock_trino, client):
        """Query records within a time window returns expected columns & rows."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:00", 1.0, 2.0, 0.0,
                 0.0, 0.0, 0.0, 0.5, "Room_A", "{}"],
                ["robot_01", "2026-03-19T10:00:10", 1.5, 2.3, 0.0,
                 0.0, 0.0, 15.0, 0.6, "Room_A", "{}"],
            ],
            "row_count": 2,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:01:00",
                "limit": 100,
                "order": "ASC",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2
        assert len(body["columns"]) == 11
        assert body["rows"][0][0] == "robot_01"

        # Verify the service was called
        mock_trino.query_dynamic_by_time_range.assert_called_once()

    @patch("app.api.v1.dynamic.trino_service")
    def test_time_range_invalid_window(self, mock_trino, client):
        """start_time >= end_time should return 400."""
        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T12:00:00",
                "end_time": "2026-03-19T10:00:00",
            },
        )
        assert resp.status_code == 400
        assert "start_time" in resp.json()["detail"]

    @patch("app.api.v1.dynamic.trino_service")
    def test_time_range_desc_order(self, mock_trino, client):
        """Query with DESC order should pass the order parameter through."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": ["object_id", "timestamp"],
            "rows": [["robot_01", "2026-03-19T10:00:40"]],
            "row_count": 1,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "order": "DESC",
            },
        )
        assert resp.status_code == 200
        mock_trino.query_dynamic_by_time_range.assert_called_once()
        call_kwargs = mock_trino.query_dynamic_by_time_range.call_args
        assert call_kwargs.kwargs.get("order") == "DESC" or call_kwargs[1].get("order") == "DESC"


# ═══════════════════════════════════════════════════════════════════════
#  Test 4: Space (Zone) Query
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicSpaceQuery:
    """Tests for POST /api/v1/dynamic/query/by-space."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_query_by_space(self, mock_trino, client):
        """Query all objects in a space returns cross-table results."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:00", 1.0, 2.0, 0.0,
                 0.0, 0.0, 0.0, 0.5, "Room_A", "{}"],
                ["worker_02", "2026-03-19T10:00:05", 3.0, 4.0, 0.0,
                 0.0, 0.0, 0.0, 1.0, "Room_A", "{}"],
            ],
            "row_count": 2,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A", "limit": 100},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2
        # Both records should be in Room_A
        assert all(row[9] == "Room_A" for row in body["rows"])

    @patch("app.api.v1.dynamic.trino_service")
    def test_query_by_space_with_time_filter(self, mock_trino, client):
        """Space query with optional time window passes all params."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": ["object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                         "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties"],
            "rows": [],
            "row_count": 0,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={
                "space_id": "Room_B",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 50,
            },
        )

        assert resp.status_code == 200
        assert resp.json()["row_count"] == 0


# ═══════════════════════════════════════════════════════════════════════
#  Test 5: Latest State Query
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicLatestQuery:
    """Tests for GET /api/v1/dynamic/query/latest."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_latest_single_object(self, mock_trino, client):
        """Query latest state for a specific object."""
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:40", 3.0, 3.2, 0.0,
                 0.0, 0.0, 60.0, 0.9, "Room_A", '{"battery": 91}'],
            ],
            "row_count": 1,
        }

        resp = client.get("/api/v1/dynamic/query/latest?object_id=robot_01")
        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 1
        assert body["rows"][0][0] == "robot_01"

    @patch("app.api.v1.dynamic.trino_service")
    def test_latest_all_objects(self, mock_trino, client):
        """Query latest state for all objects (no object_id param)."""
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:40", 3.0, 3.2, 0.0,
                 0.0, 0.0, 60.0, 0.9, "Room_A", "{}"],
                ["worker_02", "2026-03-19T10:10:00", 5.0, 6.0, 0.0,
                 0.0, 0.0, 0.0, 1.0, "Room_B", "{}"],
            ],
            "row_count": 2,
        }

        resp = client.get("/api/v1/dynamic/query/latest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2

    @patch("app.api.v1.dynamic.trino_service")
    def test_latest_service_error(self, mock_trino, client):
        """Service layer failure should propagate as 500."""
        mock_trino.query_dynamic_latest.side_effect = RuntimeError("Trino unavailable")

        resp = client.get("/api/v1/dynamic/query/latest?object_id=robot_01")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  Test 6: Trajectory Query
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicTrajectoryQuery:
    """Tests for POST /api/v1/dynamic/query/trajectory."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_raw(self, mock_trino, client):
        """Query raw trajectory (no downsampling)."""
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                         "speed", "space_id"],
            "rows": [
                ["robot_01", "2026-03-19T10:00:00", 1.0, 2.0, 0.0, 0.5, "Room_A"],
                ["robot_01", "2026-03-19T10:00:10", 1.5, 2.3, 0.0, 0.6, "Room_A"],
                ["robot_01", "2026-03-19T10:00:20", 2.0, 2.6, 0.0, 0.7, "Room_A"],
            ],
            "row_count": 3,
        }

        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:01:00",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 3
        # Verify trajectory positions are time-ordered (increasing x)
        positions_x = [row[2] for row in body["rows"]]
        assert positions_x == sorted(positions_x)

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_with_downsampling(self, mock_trino, client):
        """Query trajectory with time-bucket downsampling."""
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "time_bucket", "pos_x", "pos_y", "pos_z",
                         "speed", "sample_count"],
            "rows": [
                ["robot_01", "2026-03-19T10:00:00", 1.25, 2.15, 0.0, 0.55, 2],
                ["robot_01", "2026-03-19T10:00:30", 2.5, 2.75, 0.0, 0.75, 2],
            ],
            "row_count": 2,
        }

        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:01:00",
                "sample_interval_seconds": 30,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_invalid_time_window(self, mock_trino, client):
        """start_time >= end_time should return 400."""
        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T12:00:00",
                "end_time": "2026-03-19T10:00:00",
            },
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════
#  Test 7: Spatial Bounding Box Query
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicSpatialRangeQuery:
    """Tests for POST /api/v1/dynamic/query/spatial-range."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_spatial_range_2d(self, mock_trino, client):
        """Query objects within a 2D bounding box."""
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:10", 1.5, 2.3, 0.0,
                 0.0, 0.0, 15.0, 0.6, "Room_A", "{}"],
            ],
            "row_count": 1,
        }

        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0,
                "x_max": 5.0,
                "y_min": 0.0,
                "y_max": 5.0,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 1

    @patch("app.api.v1.dynamic.trino_service")
    def test_spatial_range_3d_with_time(self, mock_trino, client):
        """Query objects in 3D bounding box with time filter."""
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [],
            "row_count": 0,
        }

        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0,
                "x_max": 10.0,
                "y_min": 0.0,
                "y_max": 10.0,
                "z_min": -1.0,
                "z_max": 5.0,
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["row_count"] == 0

    def test_spatial_range_invalid_x(self, client):
        """x_min > x_max should return 400."""
        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={"x_min": 10.0, "x_max": 5.0, "y_min": 0.0, "y_max": 5.0},
        )
        assert resp.status_code == 400
        assert "x_min" in resp.json()["detail"]

    def test_spatial_range_invalid_y(self, client):
        """y_min > y_max should return 400."""
        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={"x_min": 0.0, "x_max": 5.0, "y_min": 10.0, "y_max": 5.0},
        )
        assert resp.status_code == 400
        assert "y_min" in resp.json()["detail"]

    def test_spatial_range_invalid_z(self, client):
        """z_min > z_max should return 400."""
        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0, "x_max": 5.0,
                "y_min": 0.0, "y_max": 5.0,
                "z_min": 10.0, "z_max": 2.0,
            },
        )
        assert resp.status_code == 400
        assert "z_min" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════
#  Test 8: Congestion Time-Series Query
# ═══════════════════════════════════════════════════════════════════════

class TestCongestionTimeseries:
    """Tests for POST /api/v1/dynamic/query/congestion-timeseries."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_congestion_all_spaces(self, mock_trino, client):
        """Congestion timeseries across all spaces."""
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 3],
                ["Room_A", "2026-03-19T10:01:00", 2],
                ["Room_B", "2026-03-19T10:00:00", 1],
                ["Room_B", "2026-03-19T10:01:00", 4],
                ["Hallway_01", "2026-03-19T10:00:00", 1],
            ],
            "row_count": 5,
        }

        resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={"bucket_seconds": 60, "limit": 1000},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 5
        assert body["columns"] == ["space_id", "time_bucket", "object_count"]

    @patch("app.api.v1.dynamic.trino_service")
    def test_congestion_single_space(self, mock_trino, client):
        """Congestion timeseries filtered by single space_id."""
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 3],
                ["Room_A", "2026-03-19T10:01:00", 2],
            ],
            "row_count": 2,
        }

        resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={
                "space_id": "Room_A",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "bucket_seconds": 60,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2
        assert all(row[0] == "Room_A" for row in body["rows"])

    @patch("app.api.v1.dynamic.trino_service")
    def test_congestion_no_data(self, mock_trino, client):
        """Congestion query returns empty when no dynamic data exists."""
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [],
            "row_count": 0,
        }

        resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={"bucket_seconds": 60},
        )

        assert resp.status_code == 200
        assert resp.json()["row_count"] == 0


# ═══════════════════════════════════════════════════════════════════════
#  Test 9: Full E2E Flow — Ingest → Query Verification
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicE2EFlow:
    """
    Full end-to-end flow: table creation → data insert → Trino query.

    Simulates the complete lifecycle of dynamic object data management.
    """

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_then_query_flow(self, mock_iceberg, mock_trino, client, sample_records):
        """
        E2E: Ingest 5 records → list objects → time-range query → latest query.

        Verifies data consistency across the full ingest→query pipeline.
        """
        # ── Step 1: Ingest records ──
        mock_iceberg.insert_dynamic_records.return_value = (5, "dynamic_robot_01")

        ingest_resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": sample_records},
        )
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["inserted"] == 5

        # ── Step 2: List objects — should now contain robot_01 ──
        mock_trino.list_dynamic_objects.return_value = [
            {
                "object_id": "robot_01",
                "table_name": "dynamic_robot_01",
                "record_count": 5,
                "first_seen": "2026-03-19T10:00:00",
                "last_seen": "2026-03-19T10:00:40",
            },
        ]

        list_resp = client.get("/api/v1/dynamic/objects")
        assert list_resp.status_code == 200
        objects = list_resp.json()["objects"]
        assert len(objects) == 1
        assert objects[0]["object_id"] == "robot_01"
        assert objects[0]["record_count"] == 5

        # ── Step 3: Time-range query — should return all 5 records ──
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", f"2026-03-19T10:00:{i*10:02d}", 1.0 + i * 0.5,
                 2.0 + i * 0.3, 0.0, 0.0, 0.0, float(i * 15),
                 0.5 + i * 0.1, "Room_A", json.dumps({"battery": 95 - i})]
                for i in range(5)
            ],
            "row_count": 5,
        }

        query_resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:01:00",
            },
        )
        assert query_resp.status_code == 200
        query_body = query_resp.json()
        assert query_body["row_count"] == 5

        # Verify row data integrity: battery decreases over time
        for i, row in enumerate(query_body["rows"]):
            props = json.loads(row[10])  # properties column
            assert props["battery"] == 95 - i

        # ── Step 4: Latest query — should return last record ──
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["robot_01", "2026-03-19T10:00:40", 3.0, 3.2, 0.0,
                 0.0, 0.0, 60.0, 0.9, "Room_A", '{"battery": 91}'],
            ],
            "row_count": 1,
        }

        latest_resp = client.get("/api/v1/dynamic/query/latest?object_id=robot_01")
        assert latest_resp.status_code == 200
        latest_body = latest_resp.json()
        assert latest_body["row_count"] == 1
        assert latest_body["rows"][0][8] == 0.9  # speed of last record
        assert json.loads(latest_body["rows"][0][10])["battery"] == 91

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    def test_multi_object_space_congestion_flow(
        self, mock_iceberg, mock_trino, client, multi_space_records
    ):
        """
        E2E: Ingest records for 5 objects across 3 spaces →
             verify space query → verify congestion timeseries.

        Space distribution:
          Room_A     → worker_00, worker_02  (2 objects)
          Room_B     → worker_01, worker_04  (2 objects)
          Hallway_01 → worker_03             (1 object)
        """
        # ── Step 1: Ingest records for each worker ──
        for rec in multi_space_records:
            obj_id = rec["object_id"]
            mock_iceberg.insert_dynamic_records.return_value = (1, f"dynamic_{obj_id}")
            resp = client.post(
                "/api/v1/dynamic/ingest",
                json={"records": [rec]},
            )
            assert resp.status_code == 200

        assert mock_iceberg.insert_dynamic_records.call_count == 5

        # ── Step 2: Space query — Room_A should have 2 objects ──
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["worker_00", "2026-03-19T10:00:00", 0.0, 0.0, 0.0,
                 0.0, 0.0, 0.0, 1.0, "Room_A", "{}"],
                ["worker_02", "2026-03-19T10:00:10", 4.0, 6.0, 0.0,
                 0.0, 0.0, 0.0, 1.0, "Room_A", "{}"],
            ],
            "row_count": 2,
        }

        space_resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A"},
        )
        assert space_resp.status_code == 200
        assert space_resp.json()["row_count"] == 2

        # ── Step 3: Congestion timeseries ──
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 2],
                ["Room_B", "2026-03-19T10:00:00", 2],
                ["Hallway_01", "2026-03-19T10:00:00", 1],
            ],
            "row_count": 3,
        }

        congestion_resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={"bucket_seconds": 60},
        )
        assert congestion_resp.status_code == 200
        congestion_body = congestion_resp.json()
        assert congestion_body["row_count"] == 3

        # Verify space distribution
        space_counts = {row[0]: row[2] for row in congestion_body["rows"]}
        assert space_counts["Room_A"] == 2
        assert space_counts["Room_B"] == 2
        assert space_counts["Hallway_01"] == 1

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_then_spatial_range_query(self, mock_iceberg, mock_trino, client):
        """
        E2E: Ingest object at known coordinates → spatial-range query finds it.
        """
        # ── Step 1: Ingest at (5.0, 10.0, 0.0) ──
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_drone_01")

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={
                "records": [{
                    "object_id": "drone_01",
                    "timestamp": "2026-03-19T10:00:00",
                    "pos_x": 5.0,
                    "pos_y": 10.0,
                    "pos_z": 0.0,
                    "speed": 2.0,
                    "space_id": "Outdoor",
                }],
            },
        )
        assert resp.status_code == 200

        # ── Step 2: Spatial query covering that point ──
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["drone_01", "2026-03-19T10:00:00", 5.0, 10.0, 0.0,
                 0.0, 0.0, 0.0, 2.0, "Outdoor", "{}"],
            ],
            "row_count": 1,
        }

        spatial_resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={"x_min": 0.0, "x_max": 20.0, "y_min": 0.0, "y_max": 20.0},
        )
        assert spatial_resp.status_code == 200
        spatial_body = spatial_resp.json()
        assert spatial_body["row_count"] == 1
        assert spatial_body["rows"][0][0] == "drone_01"
        assert spatial_body["rows"][0][2] == 5.0  # pos_x
        assert spatial_body["rows"][0][3] == 10.0  # pos_y

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_then_trajectory_query(self, mock_iceberg, mock_trino, client):
        """
        E2E: Ingest trajectory points → trajectory query returns ordered path.
        """
        base_time = datetime(2026, 3, 19, 10, 0, 0)
        trajectory_records = [
            {
                "object_id": "agv_01",
                "timestamp": (base_time + timedelta(seconds=i * 5)).isoformat(),
                "pos_x": float(i),
                "pos_y": float(i * 2),
                "pos_z": 0.0,
                "speed": 1.5,
                "space_id": "Warehouse",
            }
            for i in range(10)
        ]

        # ── Step 1: Ingest ──
        mock_iceberg.insert_dynamic_records.return_value = (10, "dynamic_agv_01")
        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": trajectory_records},
        )
        assert resp.status_code == 200
        assert resp.json()["inserted"] == 10

        # ── Step 2: Trajectory query ──
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                         "speed", "space_id"],
            "rows": [
                ["agv_01", (base_time + timedelta(seconds=i * 5)).isoformat(),
                 float(i), float(i * 2), 0.0, 1.5, "Warehouse"]
                for i in range(10)
            ],
            "row_count": 10,
        }

        traj_resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "agv_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:01:00",
            },
        )
        assert traj_resp.status_code == 200
        traj_body = traj_resp.json()
        assert traj_body["row_count"] == 10

        # Verify trajectory is spatially ordered
        x_vals = [row[2] for row in traj_body["rows"]]
        assert x_vals == sorted(x_vals), "Trajectory should be time-ordered"


# ═══════════════════════════════════════════════════════════════════════
#  Test 10: Schema Validation & Edge Cases
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicSchemaEdgeCases:
    """Edge cases for data validation and schema handling."""

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_default_values(self, mock_iceberg, client):
        """Records with only required fields use correct defaults."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_minimal_obj")

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": [{"object_id": "minimal_obj"}]},
        )

        assert resp.status_code == 200

        # Verify the record dict passed to service has defaults
        call_args = mock_iceberg.insert_dynamic_records.call_args
        record = call_args[0][1][0]
        assert record["pos_x"] == 0.0
        assert record["pos_y"] == 0.0
        assert record["pos_z"] == 0.0
        assert record["speed"] == 0.0
        assert record["space_id"] == ""
        assert record["properties"] == "{}"

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_special_characters_object_id(self, mock_iceberg, client):
        """Object IDs with hyphens are handled correctly."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_robot_arm_01")

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={
                "records": [{
                    "object_id": "robot-arm-01",
                    "pos_x": 5.0,
                    "pos_y": 3.0,
                    "space_id": "Assembly_Line",
                }],
            },
        )

        assert resp.status_code == 200
        assert resp.json()["object_id"] == "robot-arm-01"

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_large_batch(self, mock_iceberg, client):
        """Ingest a large batch of 100 records."""
        mock_iceberg.insert_dynamic_records.return_value = (100, "dynamic_fleet_bot")

        base_time = datetime(2026, 3, 19, 10, 0, 0)
        records = [
            {
                "object_id": "fleet_bot",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "pos_x": float(i % 10),
                "pos_y": float(i // 10),
                "pos_z": 0.0,
                "speed": 1.5,
                "space_id": f"Zone_{i % 5}",
            }
            for i in range(100)
        ]

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={"records": records},
        )

        assert resp.status_code == 200
        assert resp.json()["inserted"] == 100

    @patch("app.api.v1.dynamic.iceberg_service")
    def test_ingest_with_rich_properties_json(self, mock_iceberg, client):
        """Records with complex nested JSON properties pass through correctly."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_iot_sensor")

        properties = json.dumps({
            "sensor_type": "uwb",
            "accuracy_m": 0.15,
            "anchors": ["A1", "A2", "A3"],
            "metadata": {
                "firmware": "v2.1.0",
                "calibrated": True,
            },
        })

        resp = client.post(
            "/api/v1/dynamic/ingest",
            json={
                "records": [{
                    "object_id": "iot_sensor",
                    "pos_x": 7.5,
                    "pos_y": 12.0,
                    "pos_z": 2.5,
                    "space_id": "Lab_01",
                    "properties": properties,
                }],
            },
        )

        assert resp.status_code == 200

        # Verify properties string was passed through intact
        call_args = mock_iceberg.insert_dynamic_records.call_args
        record = call_args[0][1][0]
        parsed = json.loads(record["properties"])
        assert parsed["sensor_type"] == "uwb"
        assert parsed["metadata"]["firmware"] == "v2.1.0"
        assert len(parsed["anchors"]) == 3
