"""
Tests for Static object Trino SQL query service endpoints.

Covers all GET /api/v1/static/* endpoints:
  - GET /api/v1/static/prims          (list with filtering & pagination)
  - GET /api/v1/static/prims/path     (exact/prefix path match)
  - GET /api/v1/static/prims/search   (properties JSON key/value search)
  - GET /api/v1/static/prims/hierarchy (scene graph hierarchy query)
  - GET /api/v1/static/prims/latest   (latest ingestion batch)
  - GET /api/v1/static/spaces         (list all spaces with aggregates)
  - GET /api/v1/static/count          (total + per-space counts)
  - GET /api/v1/static/types          (type summary breakdown)
  - GET /api/v1/static/table-info     (Iceberg table metadata)

All tests use mocked trino_service / iceberg_service to avoid
requiring a running Lakehouse stack.
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
#  Mock Data Factories
# ═══════════════════════════════════════════════════════════════════════

def _mock_query_result(rows=None, columns=None, row_count=None) -> dict:
    """Generic mock for trino_service query functions returning QueryResponse."""
    cols = columns or ["prim_path", "type", "properties", "space_id", "ingested_at"]
    rws = rows or []
    return {
        "columns": cols,
        "rows": rws,
        "row_count": row_count if row_count is not None else len(rws),
    }


def _sample_rows(space_id="Room_A", count=3):
    """Generate sample static prim rows."""
    types = ["Mesh", "Xform", "Scope", "Camera", "DistantLight"]
    rows = []
    for i in range(count):
        t = types[i % len(types)]
        rows.append([
            f"/World/{space_id}/Obj_{i:02d}",
            t,
            '{"transform": {"translate": {"x": 0, "y": 0, "z": 0}}}',
            space_id,
            "2026-03-19T10:00:00",
        ])
    return rows


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/prims — List with filtering & pagination
# ═══════════════════════════════════════════════════════════════════════

class TestGetPrims:
    """Tests for GET /api/v1/static/prims."""

    @patch("app.api.v1.static.trino_service")
    def test_get_all_prims_no_filter(self, mock_trino, client):
        """No filters returns all prims via query_static_all."""
        rows = _sample_rows("Room_A", 3) + _sample_rows("Room_B", 2)
        mock_trino.query_static_all.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims")
        assert resp.status_code == 200

        data = resp.json()
        assert data["row_count"] == 5
        assert len(data["rows"]) == 5
        assert "prim_path" in data["columns"]

        mock_trino.query_static_all.assert_called_once_with(limit=10000, offset=0)

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_with_pagination(self, mock_trino, client):
        """Custom limit and offset are passed through."""
        mock_trino.query_static_all.return_value = _mock_query_result(
            rows=_sample_rows("Room_A", 2),
        )

        resp = client.get("/api/v1/static/prims?limit=50&offset=100")
        assert resp.status_code == 200

        mock_trino.query_static_all.assert_called_once_with(limit=50, offset=100)

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_filter_by_space_id(self, mock_trino, client):
        """Filter by space_id routes to query_static_by_space."""
        rows = _sample_rows("Room_A", 3)
        mock_trino.query_static_by_space.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims?space_id=Room_A")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 3

        mock_trino.query_static_by_space.assert_called_once_with(
            space_id="Room_A", prim_type=None, limit=10000, offset=0,
        )

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_filter_by_space_id_with_pagination(self, mock_trino, client):
        """space_id filter with offset passes offset through."""
        mock_trino.query_static_by_space.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims?space_id=Room_A&limit=20&offset=40")
        assert resp.status_code == 200

        mock_trino.query_static_by_space.assert_called_once_with(
            space_id="Room_A", prim_type=None, limit=20, offset=40,
        )

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_filter_by_type(self, mock_trino, client):
        """Filter by prim_type routes to query_static_by_type."""
        rows = [
            ["/World/Room_A/Chair", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"],
            ["/World/Room_B/Table", "Mesh", "{}", "Room_B", "2026-03-19T10:00:00"],
        ]
        mock_trino.query_static_by_type.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims?prim_type=Mesh")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 2

        mock_trino.query_static_by_type.assert_called_once_with(
            prim_type="Mesh", limit=10000, offset=0,
        )

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_filter_by_type_with_pagination(self, mock_trino, client):
        """prim_type filter with offset passes offset through."""
        mock_trino.query_static_by_type.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims?prim_type=Xform&limit=10&offset=5")
        assert resp.status_code == 200

        mock_trino.query_static_by_type.assert_called_once_with(
            prim_type="Xform", limit=10, offset=5,
        )

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_combined_space_and_type_filter(self, mock_trino, client):
        """Both space_id and prim_type combined in query_static_by_space."""
        rows = [
            ["/World/Room_A/Chair", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"],
        ]
        mock_trino.query_static_by_space.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims?space_id=Room_A&prim_type=Mesh")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 1

        mock_trino.query_static_by_space.assert_called_once_with(
            space_id="Room_A", prim_type="Mesh", limit=10000, offset=0,
        )

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_empty_result(self, mock_trino, client):
        """Returns empty response when no prims match."""
        mock_trino.query_static_all.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims")
        assert resp.status_code == 200

        data = resp.json()
        assert data["row_count"] == 0
        assert data["rows"] == []

    @patch("app.api.v1.static.trino_service")
    def test_get_prims_trino_error(self, mock_trino, client):
        """Trino error returns 500."""
        mock_trino.query_static_all.side_effect = Exception("Connection refused")

        resp = client.get("/api/v1/static/prims")
        assert resp.status_code == 500
        assert "Connection refused" in resp.json()["detail"]

    def test_get_prims_invalid_limit(self, client):
        """Invalid limit parameter returns 422."""
        resp = client.get("/api/v1/static/prims?limit=0")
        assert resp.status_code == 422

    def test_get_prims_negative_offset(self, client):
        """Negative offset returns 422."""
        resp = client.get("/api/v1/static/prims?offset=-1")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/prims/path — Path-based query
# ═══════════════════════════════════════════════════════════════════════

class TestGetPrimsByPath:
    """Tests for GET /api/v1/static/prims/path."""

    @patch("app.api.v1.static.trino_service")
    def test_exact_path_match(self, mock_trino, client):
        """Exact path match returns a single prim."""
        rows = [["/World/Room_A/Chair_01", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"]]
        mock_trino.query_static_by_prim_path.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims/path?prim_path=/World/Room_A/Chair_01")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 1

        mock_trino.query_static_by_prim_path.assert_called_once_with(
            prim_path="/World/Room_A/Chair_01", exact=True,
        )

    @patch("app.api.v1.static.trino_service")
    def test_prefix_path_match(self, mock_trino, client):
        """Prefix match returns prim and all descendants."""
        rows = [
            ["/World/Room_A", "Xform", "{}", "Room_A", "2026-03-19T10:00:00"],
            ["/World/Room_A/Chair_01", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"],
            ["/World/Room_A/Table_01", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00"],
        ]
        mock_trino.query_static_by_prim_path.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims/path?prim_path=/World/Room_A&exact=false")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 3

        mock_trino.query_static_by_prim_path.assert_called_once_with(
            prim_path="/World/Room_A", exact=False,
        )

    @patch("app.api.v1.static.trino_service")
    def test_path_not_found(self, mock_trino, client):
        """Non-existent path returns empty results (not 404)."""
        mock_trino.query_static_by_prim_path.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims/path?prim_path=/World/NonExistent")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 0

    def test_path_required_param(self, client):
        """Missing prim_path parameter returns 422."""
        resp = client.get("/api/v1/static/prims/path")
        assert resp.status_code == 422

    @patch("app.api.v1.static.trino_service")
    def test_path_trino_error(self, mock_trino, client):
        """Trino failure returns 500."""
        mock_trino.query_static_by_prim_path.side_effect = Exception("Query timeout")

        resp = client.get("/api/v1/static/prims/path?prim_path=/World/Room_A")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/prims/search — Properties JSON search
# ═══════════════════════════════════════════════════════════════════════

class TestSearchPrimsByProperties:
    """Tests for GET /api/v1/static/prims/search."""

    @patch("app.api.v1.static.trino_service")
    def test_search_by_key_only(self, mock_trino, client):
        """Search for prims that have a specific JSON key."""
        rows = [
            ["/World/Room_A/Chair", "Mesh", '{"material": "wood"}', "Room_A", "2026-03-19T10:00:00"],
        ]
        mock_trino.query_static_properties_search.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims/search?key=material")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 1

        mock_trino.query_static_properties_search.assert_called_once_with(
            search_key="material", search_value=None, space_id=None, limit=10000,
        )

    @patch("app.api.v1.static.trino_service")
    def test_search_by_key_and_value(self, mock_trino, client):
        """Search for prims with a specific key=value pair."""
        rows = [
            ["/World/Room_A/Chair", "Mesh", '{"material": "wood"}', "Room_A", "2026-03-19T10:00:00"],
        ]
        mock_trino.query_static_properties_search.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims/search?key=material&value=wood")
        assert resp.status_code == 200

        mock_trino.query_static_properties_search.assert_called_once_with(
            search_key="material", search_value="wood", space_id=None, limit=10000,
        )

    @patch("app.api.v1.static.trino_service")
    def test_search_with_space_filter(self, mock_trino, client):
        """Properties search scoped to a specific space."""
        mock_trino.query_static_properties_search.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims/search?key=visibility&space_id=Room_B")
        assert resp.status_code == 200

        mock_trino.query_static_properties_search.assert_called_once_with(
            search_key="visibility", search_value=None, space_id="Room_B", limit=10000,
        )

    @patch("app.api.v1.static.trino_service")
    def test_search_with_custom_limit(self, mock_trino, client):
        """Custom limit parameter for search."""
        mock_trino.query_static_properties_search.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims/search?key=material&limit=500")
        assert resp.status_code == 200

        mock_trino.query_static_properties_search.assert_called_once_with(
            search_key="material", search_value=None, space_id=None, limit=500,
        )

    def test_search_missing_key(self, client):
        """Missing required 'key' parameter returns 422."""
        resp = client.get("/api/v1/static/prims/search")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/prims/hierarchy — Hierarchy query
# ═══════════════════════════════════════════════════════════════════════

class TestGetPrimsHierarchy:
    """Tests for GET /api/v1/static/prims/hierarchy."""

    @patch("app.api.v1.static.trino_service")
    def test_hierarchy_default_root(self, mock_trino, client):
        """Default root_path is /World."""
        rows = [
            ["/World/Room_A", "Xform", "{}", "Room_A", "2026-03-19T10:00:00", 1],
            ["/World/Room_A/Chair", "Mesh", "{}", "Room_A", "2026-03-19T10:00:00", 2],
        ]
        mock_trino.query_static_hierarchy.return_value = _mock_query_result(
            rows=rows,
            columns=["prim_path", "type", "properties", "space_id", "ingested_at", "depth"],
        )

        resp = client.get("/api/v1/static/prims/hierarchy")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 2

        mock_trino.query_static_hierarchy.assert_called_once_with(
            root_path="/World", max_depth=None,
        )

    @patch("app.api.v1.static.trino_service")
    def test_hierarchy_custom_root_and_depth(self, mock_trino, client):
        """Custom root_path and max_depth."""
        mock_trino.query_static_hierarchy.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims/hierarchy?root_path=/World/Room_A&max_depth=3")
        assert resp.status_code == 200

        mock_trino.query_static_hierarchy.assert_called_once_with(
            root_path="/World/Room_A", max_depth=3,
        )

    def test_hierarchy_invalid_depth(self, client):
        """max_depth=0 is below minimum (1), returns 422."""
        resp = client.get("/api/v1/static/prims/hierarchy?max_depth=0")
        assert resp.status_code == 422

    @patch("app.api.v1.static.trino_service")
    def test_hierarchy_trino_error(self, mock_trino, client):
        """Trino failure returns 500."""
        mock_trino.query_static_hierarchy.side_effect = Exception("Parse error")

        resp = client.get("/api/v1/static/prims/hierarchy")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/prims/latest — Latest ingestion batch
# ═══════════════════════════════════════════════════════════════════════

class TestGetLatestIngestion:
    """Tests for GET /api/v1/static/prims/latest."""

    @patch("app.api.v1.static.trino_service")
    def test_latest_ingestion(self, mock_trino, client):
        """Returns all records from the latest ingestion batch."""
        rows = _sample_rows("Room_A", 5)
        mock_trino.query_static_latest_ingestion.return_value = _mock_query_result(rows=rows)

        resp = client.get("/api/v1/static/prims/latest")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 5

    @patch("app.api.v1.static.trino_service")
    def test_latest_ingestion_empty(self, mock_trino, client):
        """Returns empty when table is empty."""
        mock_trino.query_static_latest_ingestion.return_value = _mock_query_result(rows=[])

        resp = client.get("/api/v1/static/prims/latest")
        assert resp.status_code == 200
        assert resp.json()["row_count"] == 0

    @patch("app.api.v1.static.trino_service")
    def test_latest_ingestion_error(self, mock_trino, client):
        """Trino failure returns 500."""
        mock_trino.query_static_latest_ingestion.side_effect = Exception("Table not found")

        resp = client.get("/api/v1/static/prims/latest")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/spaces — List all spaces
# ═══════════════════════════════════════════════════════════════════════

class TestListSpaces:
    """Tests for GET /api/v1/static/spaces."""

    @patch("app.api.v1.static.trino_service")
    def test_list_spaces_success(self, mock_trino, client):
        """Returns aggregated space info."""
        mock_trino.list_static_spaces.return_value = {
            "columns": ["space_id", "prim_count", "type_count", "last_ingested"],
            "rows": [
                ["Room_A", 25, 4, "2026-03-19T10:00:00"],
                ["Room_B", 15, 3, "2026-03-19T09:30:00"],
                ["Hallway", 8, 2, None],
            ],
            "row_count": 3,
        }

        resp = client.get("/api/v1/static/spaces")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_spaces"] == 3
        assert len(data["spaces"]) == 3

        space_map = {s["space_id"]: s for s in data["spaces"]}
        assert space_map["Room_A"]["prim_count"] == 25
        assert space_map["Room_A"]["type_count"] == 4
        assert space_map["Room_A"]["last_ingested"] == "2026-03-19T10:00:00"
        assert space_map["Hallway"]["last_ingested"] is None

    @patch("app.api.v1.static.trino_service")
    def test_list_spaces_empty(self, mock_trino, client):
        """Returns empty when no spaces exist."""
        mock_trino.list_static_spaces.return_value = {
            "columns": ["space_id", "prim_count", "type_count", "last_ingested"],
            "rows": [],
            "row_count": 0,
        }

        resp = client.get("/api/v1/static/spaces")
        assert resp.status_code == 200
        assert resp.json()["total_spaces"] == 0
        assert resp.json()["spaces"] == []

    @patch("app.api.v1.static.trino_service")
    def test_list_spaces_trino_error(self, mock_trino, client):
        """Trino failure returns 500."""
        mock_trino.list_static_spaces.side_effect = Exception("Network error")

        resp = client.get("/api/v1/static/spaces")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/count — Record counts
# ═══════════════════════════════════════════════════════════════════════

class TestGetStaticCount:
    """Tests for GET /api/v1/static/count."""

    @patch("app.api.v1.static.trino_service")
    def test_count_success(self, mock_trino, client):
        """Returns total count and per-space breakdown."""
        mock_trino.query_static_count.return_value = {
            "total_count": 48,
            "space_counts": {"Room_A": 25, "Room_B": 15, "Hallway": 8},
            "space_count": 3,
        }

        resp = client.get("/api/v1/static/count")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_count"] == 48
        assert data["space_count"] == 3
        assert data["space_counts"]["Room_A"] == 25
        assert data["space_counts"]["Room_B"] == 15

    @patch("app.api.v1.static.trino_service")
    def test_count_empty_table(self, mock_trino, client):
        """Empty table returns zero counts."""
        mock_trino.query_static_count.return_value = {
            "total_count": 0,
            "space_counts": {},
            "space_count": 0,
        }

        resp = client.get("/api/v1/static/count")
        assert resp.status_code == 200
        assert resp.json()["total_count"] == 0

    @patch("app.api.v1.static.trino_service")
    def test_count_trino_error(self, mock_trino, client):
        """Trino failure returns 500."""
        mock_trino.query_static_count.side_effect = Exception("Timeout")

        resp = client.get("/api/v1/static/count")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/types — Type summary
# ═══════════════════════════════════════════════════════════════════════

class TestGetTypeSummary:
    """Tests for GET /api/v1/static/types."""

    @patch("app.api.v1.static.trino_service")
    def test_type_summary_all(self, mock_trino, client):
        """Returns type breakdown for entire scene."""
        mock_trino.query_static_type_summary.return_value = {
            "columns": ["type", "prim_count"],
            "rows": [["Mesh", 30], ["Xform", 12], ["Scope", 5], ["Camera", 1]],
            "row_count": 4,
        }

        resp = client.get("/api/v1/static/types")
        assert resp.status_code == 200

        data = resp.json()
        assert data["total_types"] == 4
        assert len(data["types"]) == 4

        type_map = {t["type"]: t["prim_count"] for t in data["types"]}
        assert type_map["Mesh"] == 30
        assert type_map["Camera"] == 1

        mock_trino.query_static_type_summary.assert_called_once_with(space_id=None)

    @patch("app.api.v1.static.trino_service")
    def test_type_summary_by_space(self, mock_trino, client):
        """Returns type breakdown scoped to a single space."""
        mock_trino.query_static_type_summary.return_value = {
            "columns": ["type", "prim_count"],
            "rows": [["Mesh", 15], ["Xform", 5]],
            "row_count": 2,
        }

        resp = client.get("/api/v1/static/types?space_id=Room_A")
        assert resp.status_code == 200
        assert resp.json()["total_types"] == 2

        mock_trino.query_static_type_summary.assert_called_once_with(space_id="Room_A")

    @patch("app.api.v1.static.trino_service")
    def test_type_summary_empty(self, mock_trino, client):
        """Returns empty when no types exist."""
        mock_trino.query_static_type_summary.return_value = {
            "columns": ["type", "prim_count"],
            "rows": [],
            "row_count": 0,
        }

        resp = client.get("/api/v1/static/types")
        assert resp.status_code == 200
        assert resp.json()["total_types"] == 0
        assert resp.json()["types"] == []


# ═══════════════════════════════════════════════════════════════════════
#  GET /api/v1/static/table-info — Table metadata
# ═══════════════════════════════════════════════════════════════════════

class TestGetTableInfo:
    """Tests for GET /api/v1/static/table-info."""

    @patch("app.api.v1.static.iceberg_service")
    def test_table_info_success(self, mock_iceberg, client):
        """Returns complete table metadata."""
        mock_iceberg.get_static_table_info.return_value = {
            "status": "ok",
            "identifier": "static_db.static_prims",
            "schema_fields": [
                {"field_id": 1, "name": "prim_path", "type": "string", "required": True},
                {"field_id": 2, "name": "type", "type": "string", "required": True},
                {"field_id": 3, "name": "properties", "type": "string", "required": False},
                {"field_id": 4, "name": "space_id", "type": "string", "required": False},
                {"field_id": 5, "name": "ingested_at", "type": "timestamp", "required": False},
            ],
            "partition_spec": "PartitionSpec(space_id_partition)",
            "snapshot_count": 3,
            "current_snapshot_id": 12345,
            "location": "s3://warehouse2/static_db/static_prims",
        }

        resp = client.get("/api/v1/static/table-info")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "ok"
        assert data["identifier"] == "static_db.static_prims"
        assert len(data["schema_fields"]) == 5
        assert data["snapshot_count"] == 3
        assert data["location"].startswith("s3://")

    @patch("app.api.v1.static.iceberg_service")
    def test_table_info_error(self, mock_iceberg, client):
        """Iceberg failure returns 500."""
        mock_iceberg.get_static_table_info.side_effect = Exception("Catalog unreachable")

        resp = client.get("/api/v1/static/table-info")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  Trino Service Unit Tests — SQL Generation Validation
# ═══════════════════════════════════════════════════════════════════════

class TestTrinoServiceStaticQueries:
    """Unit tests for trino_service static query SQL generation."""

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_all_sql(self, mock_settings, mock_exec):
        """query_static_all generates correct SQL with offset."""
        from app.services.trino_service import query_static_all

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_all(limit=50, offset=100)
        sql = mock_exec.call_args[0][0]

        assert "OFFSET 100" in sql
        assert "LIMIT 50" in sql
        assert "ORDER BY prim_path ASC" in sql
        assert "static_prims" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_by_space_sql(self, mock_settings, mock_exec):
        """query_static_by_space generates correct WHERE clause with offset."""
        from app.services.trino_service import query_static_by_space

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_by_space(space_id="Room_A", prim_type="Mesh", limit=20, offset=10)
        sql = mock_exec.call_args[0][0]

        assert "space_id = 'Room_A'" in sql
        assert "type = 'Mesh'" in sql
        assert "OFFSET 10" in sql
        assert "LIMIT 20" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_by_type_sql(self, mock_settings, mock_exec):
        """query_static_by_type generates correct SQL with offset."""
        from app.services.trino_service import query_static_by_type

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_by_type(prim_type="Xform", offset=5, limit=10)
        sql = mock_exec.call_args[0][0]

        assert "type = 'Xform'" in sql
        assert "OFFSET 5" in sql
        assert "LIMIT 10" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_by_prim_path_exact(self, mock_settings, mock_exec):
        """Exact path match uses = operator."""
        from app.services.trino_service import query_static_by_prim_path

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_by_prim_path(prim_path="/World/Room_A/Chair", exact=True)
        sql = mock_exec.call_args[0][0]

        assert "prim_path = '/World/Room_A/Chair'" in sql
        assert "LIKE" not in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_by_prim_path_prefix(self, mock_settings, mock_exec):
        """Prefix path match uses LIKE operator."""
        from app.services.trino_service import query_static_by_prim_path

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_by_prim_path(prim_path="/World/Room_A", exact=False)
        sql = mock_exec.call_args[0][0]

        assert "prim_path LIKE '/World/Room_A%'" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_properties_search_sql(self, mock_settings, mock_exec):
        """Properties search uses json_extract_scalar."""
        from app.services.trino_service import query_static_properties_search

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_properties_search(
            search_key="material", search_value="wood", space_id="Room_A", limit=500,
        )
        sql = mock_exec.call_args[0][0]

        assert "json_extract_scalar(properties, '$.material')" in sql
        assert "'wood'" in sql
        assert "space_id = 'Room_A'" in sql
        assert "LIMIT 500" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_hierarchy_with_depth(self, mock_settings, mock_exec):
        """Hierarchy query with max_depth uses cardinality filter."""
        from app.services.trino_service import query_static_hierarchy

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_hierarchy(root_path="/World", max_depth=2)
        sql = mock_exec.call_args[0][0]

        assert "prim_path LIKE '/World/%'" in sql
        assert "cardinality(split(prim_path, '/'))" in sql
        assert "depth" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_query_static_latest_ingestion_sql(self, mock_settings, mock_exec):
        """Latest ingestion query uses subquery for MAX(ingested_at)."""
        from app.services.trino_service import query_static_latest_ingestion

        mock_settings.trino_catalog = "iceberg2"
        mock_settings.iceberg_namespace = "static_db"
        mock_settings.iceberg_table_name = "static_prims"
        mock_exec.return_value = {"columns": [], "rows": [], "row_count": 0}

        query_static_latest_ingestion()
        sql = mock_exec.call_args[0][0]

        assert "MAX(ingested_at)" in sql
        assert "WHERE ingested_at = (SELECT MAX(ingested_at)" in sql

    @patch("app.services.trino_service.execute_query")
    @patch("app.services.trino_service.settings")
    def test_escape_sql_prevents_injection(self, mock_settings, mock_exec):
        """SQL escape function prevents basic injection attempts."""
        from app.services.trino_service import _escape_sql

        # Single quote escape + semicolon removal
        result = _escape_sql("Room'; DROP TABLE--")
        assert "''" in result  # single quotes are doubled
        assert ";" not in result  # semicolons are removed
        # Verify specific output
        assert result == "Room'' DROP TABLE--"
