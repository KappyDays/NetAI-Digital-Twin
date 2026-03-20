"""
Tests for Dynamic object Trino SQL query service — Sub-AC 3.

Covers:
  - Time-series queries with pagination (offset/limit) and has_more detection
  - Filtering by speed range (speed_min, speed_max)
  - Filtering by space_id within time-range queries
  - Space queries with object_type filter and pagination
  - Trajectory queries with pagination
  - Spatial range queries with pagination
  - GET variant of time-range query (query-parameter based)
  - PaginatedQueryResponse schema validation
  - Edge cases: empty results, offset beyond data, boundary conditions

Endpoints under test (all under /api/v1/dynamic):
  POST /query/time-range             — Paginated time-windowed queries with filters
  GET  /query/time-range             — GET variant for Extension UI / dashboard
  POST /query/by-space               — Paginated space queries with object_type filter
  POST /query/trajectory             — Paginated trajectory queries
  POST /query/spatial-range          — Paginated spatial bounding box queries
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
    return TestClient(app)


def _make_time_range_rows(count: int, start_offset: int = 0) -> list[list]:
    """Generate mock time-series rows for robot_01."""
    base = datetime(2026, 3, 19, 10, 0, 0)
    rows = []
    for i in range(start_offset, start_offset + count):
        rows.append([
            "robot_01",
            (base + timedelta(seconds=i * 10)).isoformat(),
            1.0 + i * 0.5,   # pos_x
            2.0 + i * 0.3,   # pos_y
            0.0,              # pos_z
            0.0, 0.0,         # rot_x, rot_y
            float(i * 15),    # rot_z
            0.5 + i * 0.1,   # speed
            "Room_A",         # space_id
            json.dumps({"battery": 95 - i}),  # properties
        ])
    return rows


_COLUMNS = [
    "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
    "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
]


# ═══════════════════════════════════════════════════════════════════════
#  Test 1: Paginated Time-Range Query (POST)
# ═══════════════════════════════════════════════════════════════════════

class TestPaginatedTimeRangeQuery:
    """Tests for POST /api/v1/dynamic/query/time-range with pagination."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_first_page_with_has_more(self, mock_trino, client):
        """First page returns has_more=True when more data exists."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(5),
            "row_count": 5,
            "offset": 0,
            "limit": 5,
            "has_more": True,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 5,
                "offset": 0,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 5
        assert body["offset"] == 0
        assert body["limit"] == 5
        assert body["has_more"] is True

    @patch("app.api.v1.dynamic.trino_service")
    def test_second_page_with_offset(self, mock_trino, client):
        """Second page with offset=5 returns remaining rows."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(3, start_offset=5),
            "row_count": 3,
            "offset": 5,
            "limit": 5,
            "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 5,
                "offset": 5,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 3
        assert body["offset"] == 5
        assert body["has_more"] is False

    @patch("app.api.v1.dynamic.trino_service")
    def test_offset_beyond_data_returns_empty(self, mock_trino, client):
        """Offset beyond available data returns empty result."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": [],
            "row_count": 0,
            "offset": 1000,
            "limit": 100,
            "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 100,
                "offset": 1000,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 0
        assert body["has_more"] is False

    @patch("app.api.v1.dynamic.trino_service")
    def test_pagination_params_passed_to_service(self, mock_trino, client):
        """Verify offset and limit are forwarded to trino_service."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
            "offset": 50, "limit": 25, "has_more": False,
        }

        client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 25,
                "offset": 50,
                "order": "DESC",
            },
        )

        mock_trino.query_dynamic_by_time_range.assert_called_once()
        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["offset"] == 50
        assert kwargs["limit"] == 25
        assert kwargs["order"] == "DESC"


# ═══════════════════════════════════════════════════════════════════════
#  Test 2: Speed Range Filtering
# ═══════════════════════════════════════════════════════════════════════

class TestSpeedRangeFilter:
    """Tests for speed_min/speed_max filtering in time-range queries."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_speed_min_filter(self, mock_trino, client):
        """Filter records with speed >= speed_min."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": [
                ["robot_01", "2026-03-19T10:00:30", 2.5, 2.9, 0.0,
                 0.0, 0.0, 45.0, 0.8, "Room_A", "{}"],
            ],
            "row_count": 1,
            "offset": 0, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "speed_min": 0.7,
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["speed_min"] == 0.7

    @patch("app.api.v1.dynamic.trino_service")
    def test_speed_range_filter(self, mock_trino, client):
        """Filter records within a speed range [min, max]."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(2),
            "row_count": 2,
            "offset": 0, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "speed_min": 0.5,
                "speed_max": 1.5,
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["speed_min"] == 0.5
        assert kwargs["speed_max"] == 1.5

    @patch("app.api.v1.dynamic.trino_service")
    def test_space_id_filter_in_time_range(self, mock_trino, client):
        """Filter time-range query by space_id."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(1),
            "row_count": 1,
            "offset": 0, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "space_id": "Room_A",
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["space_id"] == "Room_A"


# ═══════════════════════════════════════════════════════════════════════
#  Test 3: GET Time-Range Query (Extension UI / Dashboard convenience)
# ═══════════════════════════════════════════════════════════════════════

class TestGetTimeRangeQuery:
    """Tests for GET /api/v1/dynamic/query/time-range."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_get_basic_query(self, mock_trino, client):
        """GET query with required params returns paginated response."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(3),
            "row_count": 3,
            "offset": 0, "limit": 1000, "has_more": False,
        }

        resp = client.get(
            "/api/v1/dynamic/query/time-range",
            params={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 3
        assert "has_more" in body
        assert "offset" in body

    @patch("app.api.v1.dynamic.trino_service")
    def test_get_with_pagination_and_filters(self, mock_trino, client):
        """GET query with all optional params including pagination and filters."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(2),
            "row_count": 2,
            "offset": 10, "limit": 50, "has_more": True,
        }

        resp = client.get(
            "/api/v1/dynamic/query/time-range",
            params={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 50,
                "offset": 10,
                "order": "DESC",
                "speed_min": 0.5,
                "speed_max": 2.0,
                "space_id": "Room_A",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 10
        assert body["limit"] == 50
        assert body["has_more"] is True

        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["offset"] == 10
        assert kwargs["limit"] == 50
        assert kwargs["order"] == "DESC"
        assert kwargs["speed_min"] == 0.5
        assert kwargs["speed_max"] == 2.0
        assert kwargs["space_id"] == "Room_A"

    @patch("app.api.v1.dynamic.trino_service")
    def test_get_invalid_time_window(self, mock_trino, client):
        """GET with start >= end returns 400."""
        resp = client.get(
            "/api/v1/dynamic/query/time-range",
            params={
                "object_id": "robot_01",
                "start_time": "2026-03-19T12:00:00",
                "end_time": "2026-03-19T10:00:00",
            },
        )
        assert resp.status_code == 400

    def test_get_missing_required_params(self, client):
        """GET without required params returns 422."""
        resp = client.get("/api/v1/dynamic/query/time-range")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  Test 4: Paginated Space Query with object_type Filter
# ═══════════════════════════════════════════════════════════════════════

class TestPaginatedSpaceQuery:
    """Tests for POST /api/v1/dynamic/query/by-space with pagination."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_space_query_with_pagination(self, mock_trino, client):
        """Space query returns paginated results."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(3),
            "row_count": 3,
            "offset": 0, "limit": 10, "has_more": True,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A", "limit": 10, "offset": 0},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["offset"] == 0
        assert body["limit"] == 10

    @patch("app.api.v1.dynamic.trino_service")
    def test_space_query_with_object_type_filter(self, mock_trino, client):
        """Space query with object_type filter passes param to service."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
            "offset": 0, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={
                "space_id": "Room_A",
                "object_type": "person",
                "limit": 100,
                "offset": 0,
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_by_space.call_args.kwargs
        assert kwargs["object_type"] == "person"
        assert kwargs["offset"] == 0

    @patch("app.api.v1.dynamic.trino_service")
    def test_space_query_second_page(self, mock_trino, client):
        """Second page of space query returns offset and has_more."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(2),
            "row_count": 2,
            "offset": 50, "limit": 50, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A", "limit": 50, "offset": 50},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["offset"] == 50
        assert body["has_more"] is False


# ═══════════════════════════════════════════════════════════════════════
#  Test 5: Paginated Trajectory Query
# ═══════════════════════════════════════════════════════════════════════

class TestPaginatedTrajectoryQuery:
    """Tests for POST /api/v1/dynamic/query/trajectory with pagination."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_with_pagination(self, mock_trino, client):
        """Trajectory query supports pagination."""
        traj_cols = ["object_id", "timestamp", "pos_x", "pos_y", "pos_z", "speed", "space_id"]
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": traj_cols,
            "rows": [
                ["robot_01", "2026-03-19T10:00:00", 1.0, 2.0, 0.0, 0.5, "Room_A"],
                ["robot_01", "2026-03-19T10:00:10", 1.5, 2.3, 0.0, 0.6, "Room_A"],
            ],
            "row_count": 2,
            "offset": 0, "limit": 100, "has_more": True,
        }

        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:10:00",
                "limit": 100,
                "offset": 0,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["offset"] == 0

        kwargs = mock_trino.query_dynamic_trajectory.call_args.kwargs
        assert kwargs["offset"] == 0
        assert kwargs["limit"] == 100

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_offset_passed(self, mock_trino, client):
        """Verify offset is properly forwarded for trajectory query."""
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "timestamp", "pos_x", "pos_y", "pos_z", "speed", "space_id"],
            "rows": [],
            "row_count": 0,
            "offset": 200, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:10:00",
                "limit": 100,
                "offset": 200,
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_trajectory.call_args.kwargs
        assert kwargs["offset"] == 200


# ═══════════════════════════════════════════════════════════════════════
#  Test 6: Paginated Spatial Range Query
# ═══════════════════════════════════════════════════════════════════════

class TestPaginatedSpatialRangeQuery:
    """Tests for POST /api/v1/dynamic/query/spatial-range with pagination."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_spatial_range_with_pagination(self, mock_trino, client):
        """Spatial-range query supports pagination."""
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(2),
            "row_count": 2,
            "offset": 0, "limit": 50, "has_more": True,
        }

        resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0, "x_max": 10.0,
                "y_min": 0.0, "y_max": 10.0,
                "limit": 50,
                "offset": 0,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["has_more"] is True
        assert body["offset"] == 0

    @patch("app.api.v1.dynamic.trino_service")
    def test_spatial_range_offset_forwarded(self, mock_trino, client):
        """Verify offset is forwarded to trino_service for spatial queries."""
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
            "offset": 100, "limit": 50, "has_more": False,
        }

        client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0, "x_max": 10.0,
                "y_min": 0.0, "y_max": 10.0,
                "limit": 50,
                "offset": 100,
            },
        )

        kwargs = mock_trino.query_dynamic_spatial_range.call_args.kwargs
        assert kwargs["offset"] == 100
        assert kwargs["limit"] == 50


# ═══════════════════════════════════════════════════════════════════════
#  Test 7: PaginatedQueryResponse Schema Validation
# ═══════════════════════════════════════════════════════════════════════

class TestPaginatedQueryResponseSchema:
    """Tests for the PaginatedQueryResponse model."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_response_includes_all_pagination_fields(self, mock_trino, client):
        """Verify all pagination metadata fields are present in response."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(2),
            "row_count": 2,
            "offset": 10,
            "limit": 5,
            "has_more": True,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 5,
                "offset": 10,
            },
        )

        assert resp.status_code == 200
        body = resp.json()

        # All required pagination fields
        assert "columns" in body
        assert "rows" in body
        assert "row_count" in body
        assert "offset" in body
        assert "limit" in body
        assert "has_more" in body

        # Optional total_estimate can be null
        assert "total_estimate" in body

        # Types
        assert isinstance(body["columns"], list)
        assert isinstance(body["rows"], list)
        assert isinstance(body["row_count"], int)
        assert isinstance(body["offset"], int)
        assert isinstance(body["limit"], int)
        assert isinstance(body["has_more"], bool)

    @patch("app.api.v1.dynamic.trino_service")
    def test_response_backward_compatible_with_query_response(self, mock_trino, client):
        """PaginatedQueryResponse is a superset of QueryResponse fields."""
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(1),
            "row_count": 1,
            "offset": 0, "limit": 100, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        body = resp.json()
        # QueryResponse fields are all present
        assert "columns" in body
        assert "rows" in body
        assert "row_count" in body


# ═══════════════════════════════════════════════════════════════════════
#  Test 8: End-to-End Pagination Flow
# ═══════════════════════════════════════════════════════════════════════

class TestPaginationE2EFlow:
    """Test iterating through pages of dynamic query results."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_paginate_through_all_data(self, mock_trino, client):
        """
        Simulate paging through 12 records with page_size=5:
          Page 1: offset=0, limit=5  → 5 rows, has_more=True
          Page 2: offset=5, limit=5  → 5 rows, has_more=True
          Page 3: offset=10, limit=5 → 2 rows, has_more=False
        """
        pages = [
            {"rows": _make_time_range_rows(5, 0), "row_count": 5,
             "offset": 0, "limit": 5, "has_more": True},
            {"rows": _make_time_range_rows(5, 5), "row_count": 5,
             "offset": 5, "limit": 5, "has_more": True},
            {"rows": _make_time_range_rows(2, 10), "row_count": 2,
             "offset": 10, "limit": 5, "has_more": False},
        ]

        all_rows = []
        for page_data in pages:
            mock_trino.query_dynamic_by_time_range.return_value = {
                "columns": _COLUMNS, **page_data,
            }

            resp = client.post(
                "/api/v1/dynamic/query/time-range",
                json={
                    "object_id": "robot_01",
                    "start_time": "2026-03-19T10:00:00",
                    "end_time": "2026-03-19T11:00:00",
                    "limit": 5,
                    "offset": page_data["offset"],
                },
            )

            assert resp.status_code == 200
            body = resp.json()
            all_rows.extend(body["rows"])

            if not body["has_more"]:
                break

        # Total rows across all pages
        assert len(all_rows) == 12

    @patch("app.api.v1.dynamic.trino_service")
    def test_combined_filter_and_pagination(self, mock_trino, client):
        """
        Query with speed filter + space filter + pagination.
        Verifies all params are forwarded correctly.
        """
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(3),
            "row_count": 3,
            "offset": 20, "limit": 10, "has_more": False,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 10,
                "offset": 20,
                "order": "DESC",
                "speed_min": 0.5,
                "speed_max": 2.0,
                "space_id": "Room_A",
            },
        )

        assert resp.status_code == 200
        kwargs = mock_trino.query_dynamic_by_time_range.call_args.kwargs
        assert kwargs["object_id"] == "robot_01"
        assert kwargs["limit"] == 10
        assert kwargs["offset"] == 20
        assert kwargs["order"] == "DESC"
        assert kwargs["speed_min"] == 0.5
        assert kwargs["speed_max"] == 2.0
        assert kwargs["space_id"] == "Room_A"


# ═══════════════════════════════════════════════════════════════════════
#  Test 9: trino_service pagination logic (unit test)
# ═══════════════════════════════════════════════════════════════════════

class TestTrinoServicePaginationLogic:
    """Unit tests for has_more detection in trino_service functions."""

    @patch("app.services.trino_service.execute_query")
    def test_has_more_true_when_extra_row(self, mock_execute):
        """When fetch returns limit+1 rows, has_more should be True."""
        from app.services.trino_service import query_dynamic_by_time_range

        # Service fetches limit+1 (6 rows) to detect "has_more"
        mock_execute.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(6),  # limit=5, got 6 -> has_more=True
            "row_count": 6,
        }

        result = query_dynamic_by_time_range(
            object_id="robot_01",
            start_time=datetime(2026, 3, 19, 10, 0, 0),
            end_time=datetime(2026, 3, 19, 11, 0, 0),
            limit=5,
            offset=0,
        )

        assert result["has_more"] is True
        assert result["row_count"] == 5  # Trimmed to limit
        assert len(result["rows"]) == 5
        assert result["offset"] == 0
        assert result["limit"] == 5

    @patch("app.services.trino_service.execute_query")
    def test_has_more_false_when_exact_or_fewer(self, mock_execute):
        """When fetch returns <= limit rows, has_more should be False."""
        from app.services.trino_service import query_dynamic_by_time_range

        mock_execute.return_value = {
            "columns": _COLUMNS,
            "rows": _make_time_range_rows(3),
            "row_count": 3,
        }

        result = query_dynamic_by_time_range(
            object_id="robot_01",
            start_time=datetime(2026, 3, 19, 10, 0, 0),
            end_time=datetime(2026, 3, 19, 11, 0, 0),
            limit=5,
            offset=0,
        )

        assert result["has_more"] is False
        assert result["row_count"] == 3

    @patch("app.services.trino_service.execute_query")
    def test_speed_filter_in_sql(self, mock_execute):
        """Speed filters should appear in the generated SQL WHERE clause."""
        from app.services.trino_service import query_dynamic_by_time_range

        mock_execute.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
        }

        query_dynamic_by_time_range(
            object_id="robot_01",
            start_time=datetime(2026, 3, 19, 10, 0, 0),
            end_time=datetime(2026, 3, 19, 11, 0, 0),
            speed_min=0.5,
            speed_max=2.0,
            space_id="Room_A",
        )

        # Check the SQL passed to execute_query
        sql = mock_execute.call_args[0][0]
        assert "speed >= 0.5" in sql
        assert "speed <= 2.0" in sql
        assert "space_id = 'Room_A'" in sql

    @patch("app.services.trino_service.execute_query")
    def test_offset_in_sql(self, mock_execute):
        """Offset should appear in the generated SQL."""
        from app.services.trino_service import query_dynamic_by_time_range

        mock_execute.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
        }

        query_dynamic_by_time_range(
            object_id="robot_01",
            start_time=datetime(2026, 3, 19, 10, 0, 0),
            end_time=datetime(2026, 3, 19, 11, 0, 0),
            offset=50,
            limit=25,
        )

        sql = mock_execute.call_args[0][0]
        assert "OFFSET 50" in sql
        assert "LIMIT 26" in sql  # limit+1 for has_more detection

    @patch("app.services.trino_service.list_dynamic_tables")
    @patch("app.services.trino_service.execute_query")
    def test_space_query_object_type_in_sql(self, mock_execute, mock_list):
        """object_type filter should appear in space query SQL."""
        from app.services.trino_service import query_dynamic_by_space

        mock_list.return_value = ["dynamic_robot_01"]
        mock_execute.return_value = {
            "columns": _COLUMNS, "rows": [], "row_count": 0,
        }

        query_dynamic_by_space(
            space_id="Room_A",
            object_type="person",
            offset=10,
            limit=20,
        )

        sql = mock_execute.call_args[0][0]
        assert "object_type = 'person'" in sql
        assert "OFFSET 10" in sql
        assert "LIMIT 21" in sql  # limit+1

    @patch("app.services.trino_service.list_dynamic_tables")
    def test_space_query_empty_tables_returns_pagination(self, mock_list):
        """Empty table list should still return pagination metadata."""
        from app.services.trino_service import query_dynamic_by_space

        mock_list.return_value = []

        result = query_dynamic_by_space(space_id="Room_A", offset=5, limit=10)

        assert result["offset"] == 5
        assert result["limit"] == 10
        assert result["has_more"] is False
        assert result["rows"] == []
