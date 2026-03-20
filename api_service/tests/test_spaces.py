"""
Tests for the /api/v1/spaces/* endpoints.

Covers:
  - GET /api/v1/spaces/congestion/summary
  - GET /api/v1/spaces/{space_id}/objects
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


# ───────────────────────────────────────────────────────────────────────
#  Mock data factories
# ───────────────────────────────────────────────────────────────────────

def _mock_static_spaces() -> dict:
    """Simulates trino_service.list_static_spaces() response."""
    return {
        "columns": ["space_id", "prim_count", "type_count", "last_ingested"],
        "rows": [
            ["Room_A", 25, 4, "2026-03-19T10:00:00"],
            ["Room_B", 15, 3, "2026-03-19T09:30:00"],
            ["Hallway", 8, 2, "2026-03-19T09:00:00"],
        ],
        "row_count": 3,
    }


def _mock_type_summary(space_id: str = None) -> dict:
    """Simulates trino_service.query_static_type_summary() response."""
    dist = {
        "Room_A": [["Mesh", 15], ["Xform", 5], ["Scope", 3], ["Camera", 2]],
        "Room_B": [["Mesh", 10], ["Xform", 3], ["Scope", 2]],
        "Hallway": [["Mesh", 5], ["Xform", 3]],
    }
    rows = dist.get(space_id, [["Mesh", 1]])
    return {"columns": ["type", "prim_count"], "rows": rows, "row_count": len(rows)}


def _mock_space_congestion() -> dict:
    """Simulates trino_service.get_space_congestion() response."""
    return {
        "spaces": [
            {
                "space_id": "Room_A",
                "object_count": 5,
                "congestion_level": 0.625,
                "timestamp": "2026-03-19T10:05:00",
            },
            {
                "space_id": "Room_B",
                "object_count": 3,
                "congestion_level": 0.375,
                "timestamp": "2026-03-19T10:05:00",
            },
        ],
        "total_objects": 8,
        "snapshot_time": "2026-03-19T10:05:00",
    }


def _mock_static_by_space(space_id: str, **kwargs) -> dict:
    """Simulates trino_service.query_static_by_space() response."""
    rows = [
        [f"/World/{space_id}/Chair_01", "Mesh", '{"transform":{}}', space_id, "2026-03-19T10:00:00"],
        [f"/World/{space_id}/Table_01", "Mesh", '{"transform":{}}', space_id, "2026-03-19T10:00:00"],
        [f"/World/{space_id}/Group", "Xform", '{}', space_id, "2026-03-19T10:00:00"],
    ]
    return {
        "columns": ["prim_path", "type", "properties", "space_id", "ingested_at"],
        "rows": rows,
        "row_count": len(rows),
    }


def _mock_dynamic_by_space(space_id: str, **kwargs) -> dict:
    """Simulates trino_service.query_dynamic_by_space() response."""
    rows = [
        ["worker_01", "2026-03-19T10:04:00", 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.5, space_id, "{}"],
        ["worker_01", "2026-03-19T10:05:00", 1.5, 2.5, 0.0, 0.0, 0.0, 0.0, 1.2, space_id, "{}"],
        ["agv_01", "2026-03-19T10:05:00", 3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.8, space_id, '{"battery":85}'],
    ]
    return {
        "columns": [
            "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
            "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
        ],
        "rows": rows,
        "row_count": len(rows),
    }


# ───────────────────────────────────────────────────────────────────────
#  GET /api/v1/spaces/congestion/summary
# ───────────────────────────────────────────────────────────────────────

class TestCongestionSummary:
    """Tests for GET /api/v1/spaces/congestion/summary."""

    @patch("app.api.v1.spaces.trino_service")
    def test_congestion_summary_success(self, mock_trino, client):
        """Full congestion summary with both static and dynamic data."""
        mock_trino.list_static_spaces.return_value = _mock_static_spaces()
        mock_trino.query_static_type_summary.side_effect = _mock_type_summary
        mock_trino.get_space_congestion.return_value = _mock_space_congestion()

        resp = client.get("/api/v1/spaces/congestion/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert "spaces" in data
        assert data["total_spaces"] == 3  # Room_A, Room_B, Hallway
        assert data["total_static_prims"] == 48  # 25+15+8
        assert data["total_dynamic_objects"] == 8
        assert "snapshot_time" in data

        # Check individual space data
        space_map = {s["space_id"]: s for s in data["spaces"]}

        room_a = space_map["Room_A"]
        assert room_a["static_prim_count"] == 25
        assert room_a["dynamic_object_count"] == 5
        assert room_a["total_object_count"] == 30
        assert 0.0 <= room_a["congestion_level"] <= 1.0
        assert "Mesh" in room_a["type_distribution"]

        room_b = space_map["Room_B"]
        assert room_b["static_prim_count"] == 15
        assert room_b["dynamic_object_count"] == 3

        hallway = space_map["Hallway"]
        assert hallway["static_prim_count"] == 8
        assert hallway["dynamic_object_count"] == 0  # no dynamic in Hallway
        assert hallway["congestion_level"] == 0.0

    @patch("app.api.v1.spaces.trino_service")
    def test_congestion_summary_no_data(self, mock_trino, client):
        """Empty summary when no tables exist yet."""
        mock_trino.list_static_spaces.side_effect = Exception("Table does not exist")
        mock_trino.get_space_congestion.side_effect = Exception("No dynamic tables")

        resp = client.get("/api/v1/spaces/congestion/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["spaces"] == []
        assert data["total_spaces"] == 0
        assert data["total_static_prims"] == 0
        assert data["total_dynamic_objects"] == 0

    @patch("app.api.v1.spaces.trino_service")
    def test_congestion_summary_static_only(self, mock_trino, client):
        """Summary when only static data exists (no dynamic objects)."""
        mock_trino.list_static_spaces.return_value = _mock_static_spaces()
        mock_trino.query_static_type_summary.side_effect = _mock_type_summary
        mock_trino.get_space_congestion.return_value = {
            "spaces": [], "total_objects": 0,
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
        }

        resp = client.get("/api/v1/spaces/congestion/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_spaces"] == 3
        assert data["total_dynamic_objects"] == 0
        assert all(s["congestion_level"] == 0.0 for s in data["spaces"])

    @patch("app.api.v1.spaces.trino_service")
    def test_congestion_summary_dynamic_only(self, mock_trino, client):
        """Summary when only dynamic data exists (static table not yet populated)."""
        mock_trino.list_static_spaces.side_effect = Exception("Table not found")
        mock_trino.get_space_congestion.return_value = _mock_space_congestion()

        resp = client.get("/api/v1/spaces/congestion/summary")
        assert resp.status_code == 200

        data = resp.json()
        # Only spaces from dynamic data
        assert data["total_spaces"] == 2
        assert data["total_static_prims"] == 0
        assert data["total_dynamic_objects"] == 8


# ───────────────────────────────────────────────────────────────────────
#  GET /api/v1/spaces/{space_id}/objects
# ───────────────────────────────────────────────────────────────────────

class TestSpaceObjects:
    """Tests for GET /api/v1/spaces/{space_id}/objects."""

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_both(self, mock_trino, client):
        """Returns both static and dynamic objects."""
        mock_trino.query_static_by_space.return_value = _mock_static_by_space("Room_A")
        mock_trino.query_dynamic_by_space.return_value = _mock_dynamic_by_space("Room_A")

        resp = client.get("/api/v1/spaces/Room_A/objects")
        assert resp.status_code == 200

        data = resp.json()
        assert data["space_id"] == "Room_A"
        assert data["static_count"] == 3
        assert data["dynamic_count"] == 2  # worker_01 deduplicated, agv_01
        assert data["total_count"] == 5

        # Verify static objects
        paths = [o["prim_path"] for o in data["static_objects"]]
        assert "/World/Room_A/Chair_01" in paths
        assert "/World/Room_A/Table_01" in paths

        # Verify dynamic objects (latest per object_id)
        dyn_ids = {o["object_id"] for o in data["dynamic_objects"]}
        assert "worker_01" in dyn_ids
        assert "agv_01" in dyn_ids

        # worker_01 should have the latest position (second record)
        worker = next(o for o in data["dynamic_objects"] if o["object_id"] == "worker_01")
        assert worker["pos_x"] == 1.5
        assert worker["pos_y"] == 2.5

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_static_only(self, mock_trino, client):
        """Returns only static objects when include_dynamic=false."""
        mock_trino.query_static_by_space.return_value = _mock_static_by_space("Room_A")

        resp = client.get("/api/v1/spaces/Room_A/objects?include_dynamic=false")
        assert resp.status_code == 200

        data = resp.json()
        assert data["static_count"] == 3
        assert data["dynamic_count"] == 0
        assert data["dynamic_objects"] == []

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_dynamic_only(self, mock_trino, client):
        """Returns only dynamic objects when include_static=false."""
        mock_trino.query_dynamic_by_space.return_value = _mock_dynamic_by_space("Room_B")

        resp = client.get("/api/v1/spaces/Room_B/objects?include_static=false")
        assert resp.status_code == 200

        data = resp.json()
        assert data["static_count"] == 0
        assert data["static_objects"] == []
        assert data["dynamic_count"] == 2

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_empty_space(self, mock_trino, client):
        """Returns empty lists for a space with no data."""
        mock_trino.query_static_by_space.return_value = {
            "columns": ["prim_path", "type", "properties", "space_id", "ingested_at"],
            "rows": [], "row_count": 0,
        }
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [], "rows": [], "row_count": 0,
        }

        resp = client.get("/api/v1/spaces/EmptyRoom/objects")
        assert resp.status_code == 200

        data = resp.json()
        assert data["space_id"] == "EmptyRoom"
        assert data["static_count"] == 0
        assert data["dynamic_count"] == 0
        assert data["total_count"] == 0

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_graceful_degradation(self, mock_trino, client):
        """Static fails but dynamic succeeds — returns partial data."""
        mock_trino.query_static_by_space.side_effect = Exception("Trino connection timeout")
        mock_trino.query_dynamic_by_space.return_value = _mock_dynamic_by_space("Room_A")

        resp = client.get("/api/v1/spaces/Room_A/objects")
        assert resp.status_code == 200

        data = resp.json()
        assert data["static_count"] == 0  # gracefully degraded
        assert data["dynamic_count"] == 2  # dynamic still works

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_custom_limits(self, mock_trino, client):
        """Respects custom limit parameters."""
        mock_trino.query_static_by_space.return_value = {
            "columns": ["prim_path", "type", "properties", "space_id", "ingested_at"],
            "rows": [
                ["/World/Room_A/Obj_01", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"],
            ],
            "row_count": 1,
        }
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [], "rows": [], "row_count": 0,
        }

        resp = client.get("/api/v1/spaces/Room_A/objects?static_limit=5&dynamic_limit=10")
        assert resp.status_code == 200

        # Verify the limit was passed
        mock_trino.query_static_by_space.assert_called_once_with(
            space_id="Room_A", limit=5,
        )
        mock_trino.query_dynamic_by_space.assert_called_once_with(
            space_id="Room_A", limit=10,
        )

    @patch("app.api.v1.spaces.trino_service")
    def test_space_objects_dynamic_dedup_latest(self, mock_trino, client):
        """Ensures dynamic objects are deduplicated to latest record."""
        # Multiple records for same object at different times
        rows = [
            ["worker_01", "2026-03-19T10:01:00", 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, "Room_A", "{}"],
            ["worker_01", "2026-03-19T10:02:00", 2.0, 2.0, 0.0, 0.0, 0.0, 0.0, 1.5, "Room_A", "{}"],
            ["worker_01", "2026-03-19T10:03:00", 3.0, 3.0, 0.0, 0.0, 0.0, 0.0, 2.0, "Room_A", "{}"],
        ]
        mock_trino.query_static_by_space.return_value = {
            "columns": ["prim_path", "type", "properties", "space_id", "ingested_at"],
            "rows": [], "row_count": 0,
        }
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": rows,
            "row_count": 3,
        }

        resp = client.get("/api/v1/spaces/Room_A/objects")
        assert resp.status_code == 200

        data = resp.json()
        assert data["dynamic_count"] == 1  # single object, deduplicated
        worker = data["dynamic_objects"][0]
        assert worker["pos_x"] == 3.0  # latest position
        assert worker["speed"] == 2.0  # latest speed
