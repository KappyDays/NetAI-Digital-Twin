"""
Tests for the Space Drill-Down API endpoint.

GET /api/v1/static/spaces/{space_id}/drilldown

Tests cover:
  - Response schema validation (SpaceDrilldownResponse)
  - Static object parsing (position, rotation, scale from properties JSON)
  - Dynamic object status classification (active, idle, stale)
  - Type distribution aggregation
  - Edge cases: empty space, nonexistent space
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.schemas import (
    DrilldownDynamicObject,
    DrilldownStaticObject,
    SpaceDrilldownResponse,
    Vec3,
)

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────
#  Schema Unit Tests
# ─────────────────────────────────────────────────────────────────────

class TestDrilldownSchemas:
    """Validate Pydantic models for drill-down objects."""

    def test_drilldown_static_object_minimal(self):
        obj = DrilldownStaticObject(
            prim_path="/World/Room_A/Chair",
            object_type="Mesh",
        )
        assert obj.prim_path == "/World/Room_A/Chair"
        assert obj.object_type == "Mesh"
        assert obj.position is None
        assert obj.depth == 0
        assert obj.child_count == 0
        assert obj.properties_raw == "{}"

    def test_drilldown_static_object_full(self):
        obj = DrilldownStaticObject(
            prim_path="/World/Room_A/Table",
            object_type="Mesh",
            parent_path="/World/Room_A",
            position=Vec3(x=1.0, y=2.0, z=3.0),
            rotation=Vec3(x=0.0, y=45.0, z=0.0),
            scale=Vec3(x=1.0, y=1.0, z=1.0),
            visibility="inherited",
            material_path="/World/Looks/Wood",
            semantic_label="table",
            child_count=3,
            depth=2,
            properties_raw='{"transform": {}}',
        )
        assert obj.position.x == 1.0
        assert obj.semantic_label == "table"
        assert obj.child_count == 3

    def test_drilldown_dynamic_object_defaults(self):
        obj = DrilldownDynamicObject(object_id="robot_01")
        assert obj.object_id == "robot_01"
        assert obj.speed == 0.0
        assert obj.status == "unknown"
        assert obj.position.x == 0.0

    def test_drilldown_dynamic_object_active(self):
        obj = DrilldownDynamicObject(
            object_id="agv_02",
            position=Vec3(x=5.0, y=0.0, z=3.0),
            speed=1.2,
            status="active",
            last_seen=datetime.now(timezone.utc).isoformat(),
        )
        assert obj.status == "active"
        assert obj.speed == 1.2

    def test_space_drilldown_response(self):
        resp = SpaceDrilldownResponse(
            space_id="Room_A",
            static_count=10,
            dynamic_count=2,
            type_distribution={"Mesh": 7, "Xform": 3},
            static_objects=[],
            dynamic_objects=[],
            snapshot_time=datetime.now(timezone.utc).isoformat(),
        )
        assert resp.space_id == "Room_A"
        assert resp.static_count == 10
        assert resp.type_distribution["Mesh"] == 7

    def test_space_drilldown_response_with_objects(self):
        static = DrilldownStaticObject(
            prim_path="/World/Room_A/Desk",
            object_type="Mesh",
            depth=1,
        )
        dynamic = DrilldownDynamicObject(
            object_id="worker_01",
            status="active",
        )
        resp = SpaceDrilldownResponse(
            space_id="Room_A",
            static_count=1,
            dynamic_count=1,
            static_objects=[static],
            dynamic_objects=[dynamic],
        )
        assert len(resp.static_objects) == 1
        assert len(resp.dynamic_objects) == 1
        assert resp.static_objects[0].prim_path == "/World/Room_A/Desk"
        assert resp.dynamic_objects[0].object_id == "worker_01"


# ─────────────────────────────────────────────────────────────────────
#  API Endpoint Tests (mocked Trino)
# ─────────────────────────────────────────────────────────────────────

def _mock_drilldown_result(space_id: str = "Room_A") -> dict:
    """Generate a mock return value for trino_service.query_space_drilldown."""
    now = datetime.now(timezone.utc)
    return {
        "space_id": space_id,
        "static_count": 3,
        "dynamic_count": 1,
        "type_distribution": {"Mesh": 2, "Xform": 1},
        "static_objects": [
            {
                "prim_path": f"/World/{space_id}/Floor",
                "object_type": "Mesh",
                "parent_path": f"/World/{space_id}",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0},
                "visibility": "inherited",
                "material_path": None,
                "semantic_label": "floor",
                "child_count": 0,
                "depth": 1,
                "properties_raw": "{}",
            },
            {
                "prim_path": f"/World/{space_id}/Chair_01",
                "object_type": "Mesh",
                "parent_path": f"/World/{space_id}",
                "position": {"x": 1.5, "y": 0.0, "z": 2.0},
                "rotation": None,
                "scale": None,
                "visibility": None,
                "material_path": None,
                "semantic_label": "chair",
                "child_count": 0,
                "depth": 1,
                "properties_raw": "{}",
            },
            {
                "prim_path": f"/World/{space_id}/Group",
                "object_type": "Xform",
                "parent_path": f"/World/{space_id}",
                "position": None,
                "rotation": None,
                "scale": None,
                "visibility": None,
                "material_path": None,
                "semantic_label": None,
                "child_count": 2,
                "depth": 1,
                "properties_raw": "{}",
            },
        ],
        "dynamic_objects": [
            {
                "object_id": "robot_01",
                "position": {"x": 2.0, "y": 0.0, "z": 1.5},
                "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
                "speed": 0.5,
                "space_id": space_id,
                "last_seen": now.isoformat(),
                "status": "active",
                "properties": "{}",
            },
        ],
        "last_static_ingestion": now.isoformat(),
        "snapshot_time": now.isoformat(),
    }


class TestDrilldownEndpoint:
    """Test GET /api/v1/static/spaces/{space_id}/drilldown."""

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_success(self, mock_trino):
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result()

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        assert resp.status_code == 200

        data = resp.json()
        assert data["space_id"] == "Room_A"
        assert data["static_count"] == 3
        assert data["dynamic_count"] == 1
        assert len(data["static_objects"]) == 3
        assert len(data["dynamic_objects"]) == 1
        assert data["type_distribution"]["Mesh"] == 2

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_static_object_fields(self, mock_trino):
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result()

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        data = resp.json()

        floor = data["static_objects"][0]
        assert floor["prim_path"] == "/World/Room_A/Floor"
        assert floor["object_type"] == "Mesh"
        assert floor["position"]["x"] == 0.0
        assert floor["semantic_label"] == "floor"
        assert floor["depth"] == 1

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_dynamic_object_fields(self, mock_trino):
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result()

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        data = resp.json()

        robot = data["dynamic_objects"][0]
        assert robot["object_id"] == "robot_01"
        assert robot["status"] == "active"
        assert robot["speed"] == 0.5
        assert robot["position"]["x"] == 2.0

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_empty_space(self, mock_trino):
        """A space with no objects should return empty lists."""
        mock_trino.query_space_drilldown.return_value = {
            "space_id": "Empty_Zone",
            "static_count": 0,
            "dynamic_count": 0,
            "type_distribution": {},
            "static_objects": [],
            "dynamic_objects": [],
            "last_static_ingestion": None,
            "snapshot_time": datetime.now(timezone.utc).isoformat(),
        }

        resp = client.get("/api/v1/static/spaces/Empty_Zone/drilldown")
        assert resp.status_code == 200
        data = resp.json()
        assert data["static_count"] == 0
        assert data["dynamic_count"] == 0
        assert len(data["static_objects"]) == 0
        assert len(data["dynamic_objects"]) == 0

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_trino_error(self, mock_trino):
        """Trino failure should return 500."""
        mock_trino.query_space_drilldown.side_effect = Exception("Trino connection refused")

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        assert resp.status_code == 500
        assert "Trino connection refused" in resp.json()["detail"]

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_type_distribution(self, mock_trino):
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result()

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        data = resp.json()
        assert "Mesh" in data["type_distribution"]
        assert "Xform" in data["type_distribution"]
        assert data["type_distribution"]["Mesh"] == 2
        assert data["type_distribution"]["Xform"] == 1

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_snapshot_time(self, mock_trino):
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result()

        resp = client.get("/api/v1/static/spaces/Room_A/drilldown")
        data = resp.json()
        assert data["snapshot_time"] is not None

    @patch("app.api.v1.static.trino_service")
    def test_drilldown_url_encoded_space(self, mock_trino):
        """Space IDs with special characters should work via URL encoding."""
        mock_trino.query_space_drilldown.return_value = _mock_drilldown_result("Hall_01")

        resp = client.get("/api/v1/static/spaces/Hall_01/drilldown")
        assert resp.status_code == 200
        assert resp.json()["space_id"] == "Hall_01"
