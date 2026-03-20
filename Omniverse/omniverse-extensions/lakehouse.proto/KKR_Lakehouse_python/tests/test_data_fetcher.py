"""
Tests for the data_fetcher module.

Verifies:
  1. CongestionSummary response parsing from /spaces/congestion/summary
  2. Simple congestion response parsing from /congestion
  3. Demo data generation
  4. SpaceObjectsData parsing from /spaces/{id}/objects
  5. Two-tier fallback strategy (summary → congestion → demo)
  6. HTTP retry logic for transient errors
  7. FetchResult metadata (elapsed_ms, source, status_code)
  8. Dataclass properties (display_name, congestion_label, etc.)

All tests use unittest.mock to patch urllib — no real HTTP calls.
"""

import json
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

# Module under test — import from relative package
import sys
import os

# Add parent directory to path so we can import the module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_fetcher import (
    CongestionFetcher,
    CongestionSummary,
    DynamicObjectData,
    FetchResult,
    SpaceCongestionData,
    SpaceObjectsData,
    StaticObjectData,
    _parse_congestion_simple,
    _parse_congestion_summary,
    _parse_space_objects,
    generate_demo_summary,
)


# ═════════════════════════════════════════════════════════════════════════
#  Helpers
# ═════════════════════════════════════════════════════════════════════════

def _mock_response(status: int, data: dict):
    """Create a mock urllib response."""
    body = json.dumps(data).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.getcode.return_value = status
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


SUMMARY_RESPONSE = {
    "spaces": [
        {
            "space_id": "Room_A",
            "static_prim_count": 42,
            "dynamic_object_count": 3,
            "total_object_count": 45,
            "congestion_level": 0.25,
            "type_distribution": {"Mesh": 30, "Xform": 12},
        },
        {
            "space_id": "Hallway_01",
            "static_prim_count": 10,
            "dynamic_object_count": 8,
            "total_object_count": 18,
            "congestion_level": 0.80,
            "type_distribution": {"Mesh": 8, "Xform": 2},
        },
    ],
    "total_spaces": 2,
    "total_static_prims": 52,
    "total_dynamic_objects": 11,
    "snapshot_time": "2026-03-19T12:00:00",
}

SIMPLE_CONGESTION_RESPONSE = {
    "spaces": [
        {
            "space_id": "Room_A",
            "object_count": 5,
            "congestion_level": 0.45,
            "timestamp": "2026-03-19T12:00:00+00:00",
        },
        {
            "space_id": "Room_B",
            "object_count": 2,
            "congestion_level": 0.18,
            "timestamp": "2026-03-19T12:00:00+00:00",
        },
    ],
    "total_objects": 7,
    "snapshot_time": "2026-03-19T12:00:00+00:00",
}

SPACE_OBJECTS_RESPONSE = {
    "space_id": "Room_A",
    "static_objects": [
        {"prim_path": "/World/Room_A/Chair_01", "object_type": "Mesh", "properties": "{}"},
        {"prim_path": "/World/Room_A/Table_01", "object_type": "Mesh", "properties": "{}"},
    ],
    "dynamic_objects": [
        {"object_id": "robot_01", "pos_x": 1.0, "pos_y": 2.0, "pos_z": 0.0, "speed": 0.5},
    ],
    "static_count": 2,
    "dynamic_count": 1,
    "total_count": 3,
}


# ═════════════════════════════════════════════════════════════════════════
#  Test: Response Parsers
# ═════════════════════════════════════════════════════════════════════════

class TestParseCongestionSummary(unittest.TestCase):
    """Test _parse_congestion_summary with the rich endpoint response."""

    def test_parse_spaces(self):
        result = _parse_congestion_summary(SUMMARY_RESPONSE)
        self.assertEqual(len(result.spaces), 2)
        self.assertEqual(result.total_spaces, 2)
        self.assertEqual(result.source, "summary")

    def test_space_fields(self):
        result = _parse_congestion_summary(SUMMARY_RESPONSE)
        room_a = result.spaces[0]
        self.assertEqual(room_a.space_id, "Room_A")
        self.assertEqual(room_a.static_prim_count, 42)
        self.assertEqual(room_a.dynamic_object_count, 3)
        self.assertEqual(room_a.total_object_count, 45)
        self.assertAlmostEqual(room_a.congestion_level, 0.25)
        self.assertEqual(room_a.type_distribution, {"Mesh": 30, "Xform": 12})

    def test_totals(self):
        result = _parse_congestion_summary(SUMMARY_RESPONSE)
        self.assertEqual(result.total_static_prims, 52)
        self.assertEqual(result.total_dynamic_objects, 11)
        self.assertEqual(result.total_objects, 63)

    def test_empty_response(self):
        result = _parse_congestion_summary({"spaces": []})
        self.assertEqual(len(result.spaces), 0)
        self.assertEqual(result.total_spaces, 0)


class TestParseCongestionSimple(unittest.TestCase):
    """Test _parse_congestion_simple with the fallback endpoint response."""

    def test_parse_spaces(self):
        result = _parse_congestion_simple(SIMPLE_CONGESTION_RESPONSE)
        self.assertEqual(len(result.spaces), 2)
        self.assertEqual(result.source, "congestion")

    def test_space_fields(self):
        result = _parse_congestion_simple(SIMPLE_CONGESTION_RESPONSE)
        room_a = result.spaces[0]
        self.assertEqual(room_a.space_id, "Room_A")
        self.assertEqual(room_a.object_count, 5)
        self.assertEqual(room_a.dynamic_object_count, 5)
        self.assertAlmostEqual(room_a.congestion_level, 0.45)

    def test_totals(self):
        result = _parse_congestion_simple(SIMPLE_CONGESTION_RESPONSE)
        self.assertEqual(result.total_dynamic_objects, 7)


class TestParseSpaceObjects(unittest.TestCase):
    """Test _parse_space_objects with per-space drill-down response."""

    def test_parse_static_objects(self):
        result = _parse_space_objects(SPACE_OBJECTS_RESPONSE)
        self.assertEqual(len(result.static_objects), 2)
        self.assertEqual(result.static_objects[0].prim_path, "/World/Room_A/Chair_01")
        self.assertEqual(result.static_objects[0].object_type, "Mesh")

    def test_parse_dynamic_objects(self):
        result = _parse_space_objects(SPACE_OBJECTS_RESPONSE)
        self.assertEqual(len(result.dynamic_objects), 1)
        self.assertEqual(result.dynamic_objects[0].object_id, "robot_01")
        self.assertAlmostEqual(result.dynamic_objects[0].pos_x, 1.0)
        self.assertAlmostEqual(result.dynamic_objects[0].speed, 0.5)

    def test_counts(self):
        result = _parse_space_objects(SPACE_OBJECTS_RESPONSE)
        self.assertEqual(result.static_count, 2)
        self.assertEqual(result.dynamic_count, 1)
        self.assertEqual(result.total_count, 3)


# ═════════════════════════════════════════════════════════════════════════
#  Test: Dataclass Properties
# ═════════════════════════════════════════════════════════════════════════

class TestSpaceCongestionData(unittest.TestCase):
    """Test SpaceCongestionData computed properties."""

    def test_display_name_with_prefix(self):
        s = SpaceCongestionData(space_id="/World/Room_A")
        self.assertEqual(s.display_name, "Room_A")

    def test_display_name_without_prefix(self):
        s = SpaceCongestionData(space_id="Room_A")
        self.assertEqual(s.display_name, "Room_A")

    def test_congestion_label_low(self):
        s = SpaceCongestionData(space_id="X", congestion_level=0.2)
        self.assertEqual(s.congestion_label, "Low")

    def test_congestion_label_medium(self):
        s = SpaceCongestionData(space_id="X", congestion_level=0.5)
        self.assertEqual(s.congestion_label, "Medium")

    def test_congestion_label_high(self):
        s = SpaceCongestionData(space_id="X", congestion_level=0.8)
        self.assertEqual(s.congestion_label, "High")


class TestCongestionSummary(unittest.TestCase):
    """Test CongestionSummary computed properties."""

    def test_max_object_count(self):
        s = CongestionSummary(spaces=[
            SpaceCongestionData(space_id="A", total_object_count=10),
            SpaceCongestionData(space_id="B", total_object_count=50),
        ])
        self.assertEqual(s.max_object_count, 50)

    def test_max_object_count_empty(self):
        s = CongestionSummary()
        self.assertEqual(s.max_object_count, 0)

    def test_get_space(self):
        s = CongestionSummary(spaces=[
            SpaceCongestionData(space_id="A"),
            SpaceCongestionData(space_id="B"),
        ])
        self.assertIsNotNone(s.get_space("A"))
        self.assertIsNone(s.get_space("C"))

    def test_sorted_by_congestion(self):
        s = CongestionSummary(spaces=[
            SpaceCongestionData(space_id="A", congestion_level=0.1),
            SpaceCongestionData(space_id="B", congestion_level=0.9),
            SpaceCongestionData(space_id="C", congestion_level=0.5),
        ])
        sorted_spaces = s.sorted_by_congestion()
        self.assertEqual([x.space_id for x in sorted_spaces], ["B", "C", "A"])

    def test_to_dict(self):
        s = CongestionSummary(
            spaces=[SpaceCongestionData(space_id="A", total_object_count=10)],
            total_spaces=1,
            source="test",
        )
        d = s.to_dict()
        self.assertEqual(d["total_spaces"], 1)
        self.assertEqual(d["source"], "test")
        self.assertEqual(len(d["spaces"]), 1)


# ═════════════════════════════════════════════════════════════════════════
#  Test: Demo Data Generator
# ═════════════════════════════════════════════════════════════════════════

class TestDemoData(unittest.TestCase):
    """Test generate_demo_summary for offline fallback."""

    def test_demo_has_spaces(self):
        demo = generate_demo_summary()
        self.assertGreater(len(demo.spaces), 0)
        self.assertEqual(demo.source, "demo")

    def test_demo_spaces_have_required_fields(self):
        demo = generate_demo_summary()
        for space in demo.spaces:
            self.assertIsInstance(space.space_id, str)
            self.assertGreaterEqual(space.total_object_count, 0)
            self.assertGreaterEqual(space.congestion_level, 0.0)
            self.assertLessEqual(space.congestion_level, 1.0)

    def test_demo_totals_are_consistent(self):
        demo = generate_demo_summary()
        self.assertEqual(demo.total_spaces, len(demo.spaces))
        expected_static = sum(s.static_prim_count for s in demo.spaces)
        self.assertEqual(demo.total_static_prims, expected_static)


# ═════════════════════════════════════════════════════════════════════════
#  Test: CongestionFetcher Integration
# ═════════════════════════════════════════════════════════════════════════

class TestCongestionFetcher(unittest.TestCase):
    """Test CongestionFetcher with mocked HTTP responses."""

    def setUp(self):
        self.status_log = []
        self.fetcher = CongestionFetcher(
            api_base="http://test-api:8000",
            timeout=5,
            use_demo_fallback=True,
            on_status=self.status_log.append,
        )

    @patch("data_fetcher.urllib.request.urlopen")
    def test_fetch_summary_primary(self, mock_urlopen):
        """Primary endpoint returns rich summary data."""
        mock_urlopen.return_value = _mock_response(200, SUMMARY_RESPONSE)

        result = self.fetcher.fetch_summary()

        self.assertTrue(result.success)
        self.assertEqual(result.source, "summary")
        self.assertEqual(result.status_code, 200)
        self.assertIsInstance(result.data, CongestionSummary)
        self.assertEqual(len(result.data.spaces), 2)
        self.assertGreaterEqual(result.elapsed_ms, 0)

    @patch("data_fetcher.urllib.request.urlopen")
    def test_fetch_summary_fallback(self, mock_urlopen):
        """When primary fails, falls back to simple congestion endpoint."""
        import urllib.error

        # First call (summary) fails, second call (congestion) succeeds
        call_count = [0]

        def side_effect(req, timeout=None):
            call_count[0] += 1
            if call_count[0] <= 3:  # First call + 2 retries for summary
                raise urllib.error.URLError("Connection refused")
            return _mock_response(200, SIMPLE_CONGESTION_RESPONSE)

        mock_urlopen.side_effect = side_effect

        result = self.fetcher.fetch_summary()

        self.assertTrue(result.success)
        self.assertEqual(result.source, "fallback")
        self.assertIsInstance(result.data, CongestionSummary)

    @patch("data_fetcher.urllib.request.urlopen")
    def test_fetch_summary_demo_fallback(self, mock_urlopen):
        """When both endpoints fail, returns demo data."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = self.fetcher.fetch_summary()

        self.assertTrue(result.success)
        self.assertEqual(result.source, "demo")
        self.assertIsInstance(result.data, CongestionSummary)

    @patch("data_fetcher.urllib.request.urlopen")
    def test_fetch_summary_no_demo(self, mock_urlopen):
        """When demo fallback disabled, returns failure."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        fetcher = CongestionFetcher(
            api_base="http://test:8000",
            use_demo_fallback=False,
        )
        result = fetcher.fetch_summary()

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    @patch("data_fetcher.urllib.request.urlopen")
    def test_fetch_space_objects(self, mock_urlopen):
        """Per-space objects endpoint works correctly."""
        mock_urlopen.return_value = _mock_response(200, SPACE_OBJECTS_RESPONSE)

        result = self.fetcher.fetch_space_objects("Room_A")

        self.assertTrue(result.success)
        self.assertIsInstance(result.data, SpaceObjectsData)
        self.assertEqual(result.data.space_id, "Room_A")
        self.assertEqual(result.data.static_count, 2)
        self.assertEqual(result.data.dynamic_count, 1)

    @patch("data_fetcher.urllib.request.urlopen")
    def test_check_health_ok(self, mock_urlopen):
        """Health check returns success."""
        mock_urlopen.return_value = _mock_response(200, {"status": "ok"})

        result = self.fetcher.check_health()

        self.assertTrue(result.success)
        self.assertEqual(result.data["status"], "ok")

    @patch("data_fetcher.urllib.request.urlopen")
    def test_check_health_fail(self, mock_urlopen):
        """Health check returns failure on connection error."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        result = self.fetcher.check_health()

        self.assertFalse(result.success)

    def test_api_base_property(self):
        """API base URL can be updated dynamically."""
        self.assertEqual(self.fetcher.api_base, "http://test-api:8000")
        self.fetcher.api_base = "http://new-api:9000/"
        self.assertEqual(self.fetcher.api_base, "http://new-api:9000")

    @patch("data_fetcher.urllib.request.urlopen")
    def test_status_callback_called(self, mock_urlopen):
        """Status callback is invoked during fetch."""
        mock_urlopen.return_value = _mock_response(200, SUMMARY_RESPONSE)

        self.fetcher.fetch_summary()

        self.assertGreater(len(self.status_log), 0)
        self.assertTrue(any("[OK]" in msg for msg in self.status_log))


if __name__ == "__main__":
    unittest.main()
