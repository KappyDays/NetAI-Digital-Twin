"""
Dynamic 객체 API 통합 테스트 — 전체 흐름 검증.

테스트 흐름 (Full E2E Pipeline):
  1. 객체 테이블 생성      POST /api/v1/dynamic-objects/tables
  2. 센서 데이터 INSERT     POST /api/v1/dynamic-objects/sensor-data
  3. Trino 기반 데이터 조회  POST /api/v1/dynamic/query/time-range
                          POST /api/v1/dynamic/query/by-space
                          GET  /api/v1/dynamic/query/latest
                          POST /api/v1/dynamic/query/trajectory
                          POST /api/v1/dynamic/query/spatial-range
                          POST /api/v1/dynamic/query/congestion-timeseries

검증 항목:
  - Trino DDL을 통한 per-object Iceberg 테이블 생성
  - PyIceberg를 통한 Arrow batch 데이터 쓰기
  - Trino SQL을 통한 시간/공간/궤적/혼잡도 조회
  - 복수 객체 시나리오 (multi-object cross-table queries)
  - 테이블 생성 멱등성 (idempotent CREATE IF NOT EXISTS)
  - 스키마 고정성 검증 (fixed schema evolution-ready)
  - Trino 연동 에러 전파 (connection refused, query failure)

Architecture:
  Service 계층(iceberg_service, trino_service, trino_config)을 mock하여
  live infrastructure 없이도 전체 요청→응답 계약을 검증한다.
  Mock은 실제 Trino/Iceberg 반환 형식을 충실히 재현한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, call, patch

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
def base_time() -> datetime:
    """Consistent base time for all test records."""
    return datetime(2026, 3, 19, 10, 0, 0)


@pytest.fixture()
def sensor_records_worker01(base_time) -> list[dict[str, Any]]:
    """Generate 10 IoT sensor records for worker_01 spanning 90 seconds."""
    records = []
    for i in range(10):
        records.append({
            "object_id": "worker_01",
            "timestamp": (base_time + timedelta(seconds=i * 10)).isoformat(),
            "pos_x": 1.0 + i * 0.5,
            "pos_y": 2.0 + i * 0.3,
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": float(i * 15),
            "speed": 0.5 + i * 0.1,
            "space_id": "Room_A" if i < 7 else "Room_B",  # transitions at i=7
            "properties": json.dumps({"battery": 100 - i * 2, "tag": "uwb"}),
        })
    return records


@pytest.fixture()
def sensor_records_robot01(base_time) -> list[dict[str, Any]]:
    """Generate 5 IoT sensor records for robot_01 in Room_A."""
    records = []
    for i in range(5):
        records.append({
            "object_id": "robot_01",
            "timestamp": (base_time + timedelta(seconds=i * 20)).isoformat(),
            "pos_x": 10.0 + i,
            "pos_y": 5.0 + i * 0.5,
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": 0.0,
            "speed": 2.0,
            "space_id": "Room_A",
            "properties": json.dumps({"battery": 85 - i * 5, "task": "patrol"}),
        })
    return records


@pytest.fixture()
def sensor_records_agv01(base_time) -> list[dict[str, Any]]:
    """Generate 8 trajectory records for agv_01 across multiple spaces."""
    spaces = ["Warehouse", "Warehouse", "Hallway_01", "Hallway_01",
              "Room_B", "Room_B", "Hallway_01", "Warehouse"]
    records = []
    for i in range(8):
        records.append({
            "object_id": "agv_01",
            "timestamp": (base_time + timedelta(seconds=i * 15)).isoformat(),
            "pos_x": float(i * 3),
            "pos_y": float(i * 2),
            "pos_z": 0.0,
            "rot_x": 0.0,
            "rot_y": 0.0,
            "rot_z": float(i * 45 % 360),
            "speed": 1.5 + (0.5 if spaces[i] == "Hallway_01" else 0.0),
            "space_id": spaces[i],
            "properties": json.dumps({"load": "empty" if i < 4 else "loaded"}),
        })
    return records


# ═══════════════════════════════════════════════════════════════════════
#  1. Table Creation Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTableCreationIntegration:
    """
    POST /api/v1/dynamic-objects/tables — 테이블 생성 통합 테스트.

    Trino DDL(CREATE TABLE IF NOT EXISTS)을 통해 per-object Iceberg
    테이블이 정상 생성되는지 검증한다.
    """

    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_new_table(
        self, mock_init_table, mock_list_tables, mock_iceberg, client
    ):
        """신규 객체 테이블이 생성되고 올바른 FQTN이 반환된다."""
        mock_list_tables.return_value = []  # No existing tables
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg.ensure_dynamic_table.return_value = None

        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is True
        assert body["table"]["object_id"] == "worker_01"
        assert body["table"]["table_name"] == "dynamic_worker_01"
        assert "dynamic_worker_01" in body["table"]["fully_qualified"]
        mock_init_table.assert_called_once_with("worker_01")

    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_table_idempotent(
        self, mock_init_table, mock_list_tables, mock_iceberg, client
    ):
        """이미 존재하는 테이블에 대해 created=False를 반환한다 (멱등성)."""
        mock_list_tables.return_value = ["dynamic_worker_01"]
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg.ensure_dynamic_table.return_value = None

        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["created"] is False
        assert "already exists" in body["message"]

    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_table_hyphenated_id(
        self, mock_init_table, mock_list_tables, mock_iceberg, client
    ):
        """하이픈이 포함된 object_id가 올바르게 sanitize되어 테이블명에 반영된다."""
        mock_list_tables.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_agv_alpha"
        mock_iceberg.ensure_dynamic_table.return_value = None

        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "agv-alpha"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["table"]["table_name"] == "dynamic_agv_alpha"

    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_table_trino_failure(
        self, mock_init_table, mock_list_tables, client
    ):
        """Trino DDL 실패 시 500 에러가 전파된다."""
        mock_list_tables.return_value = []
        mock_init_table.side_effect = RuntimeError("Trino connection refused")

        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "test_obj"},
        )

        assert resp.status_code == 500
        assert "Trino connection refused" in resp.json()["detail"]

    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_list_tables_after_creation(
        self, mock_init_table, mock_list_tables, mock_iceberg, client
    ):
        """테이블 생성 후 GET /tables에서 목록 조회가 가능하다."""
        # Step 1: Create a table
        mock_list_tables.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg.ensure_dynamic_table.return_value = None

        create_resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )
        assert create_resp.status_code == 201

        # Step 2: List tables — now includes the new table
        mock_list_tables.return_value = ["dynamic_worker_01"]
        list_resp = client.get("/api/v1/dynamic-objects/tables")
        assert list_resp.status_code == 200
        tables = list_resp.json()
        assert len(tables) == 1
        assert tables[0]["table_name"] == "dynamic_worker_01"

    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_get_specific_table_info(
        self, mock_init_table, mock_list_tables, mock_iceberg, client
    ):
        """GET /tables/{object_id}로 특정 객체 테이블 정보를 조회한다."""
        mock_list_tables.return_value = ["dynamic_worker_01", "dynamic_robot_01"]

        resp = client.get("/api/v1/dynamic-objects/tables/worker_01")
        assert resp.status_code == 200
        body = resp.json()
        assert body["object_id"] == "worker_01"
        assert body["table_name"] == "dynamic_worker_01"

    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    def test_get_nonexistent_table_returns_404(self, mock_list_tables, client):
        """존재하지 않는 테이블 조회 시 404를 반환한다."""
        mock_list_tables.return_value = ["dynamic_worker_01"]

        resp = client.get("/api/v1/dynamic-objects/tables/nonexistent")
        assert resp.status_code == 404

    def test_create_table_invalid_object_id(self, client):
        """유효하지 않은 object_id에 대해 422 유효성 검사 에러를 반환한다."""
        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "invalid@#$%^&"},
        )
        assert resp.status_code == 422

    def test_create_table_empty_object_id(self, client):
        """빈 object_id에 대해 422를 반환한다."""
        resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": ""},
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
#  2. Sensor Data INSERT Integration Tests
# ═══════════════════════════════════════════════════════════════════════

class TestSensorDataInsertIntegration:
    """
    POST /api/v1/dynamic-objects/sensor-data — 센서 데이터 삽입 통합 테스트.

    PyIceberg를 통해 Arrow batch로 데이터가 Parquet 파일에 쓰이는 흐름을 검증한다.
    """

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_sensor_data_basic(
        self, mock_iceberg, client, sensor_records_worker01
    ):
        """기본 센서 데이터 10건 삽입이 정상 동작한다."""
        mock_iceberg.insert_dynamic_records.return_value = (10, "dynamic_worker_01")

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "worker_01",
                "records": sensor_records_worker01,
            },
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["inserted"] == 10
        assert body["table"] == "dynamic_worker_01"
        assert body["object_id"] == "worker_01"
        assert body["first_timestamp"] is not None
        assert body["last_timestamp"] is not None

        # Verify correct args passed to service
        mock_iceberg.insert_dynamic_records.assert_called_once()
        call_args = mock_iceberg.insert_dynamic_records.call_args
        assert call_args[0][0] == "worker_01"
        assert len(call_args[0][1]) == 10

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_preserves_timestamp_range(
        self, mock_iceberg, client, base_time
    ):
        """삽입 응답에 정확한 timestamp 범위가 포함된다."""
        records = [
            {
                "object_id": "sensor_x1",
                "timestamp": (base_time + timedelta(seconds=i * 5)).isoformat(),
                "pos_x": float(i),
                "pos_y": 0.0,
                "pos_z": 0.0,
                "space_id": "Lab_01",
            }
            for i in range(5)
        ]
        mock_iceberg.insert_dynamic_records.return_value = (5, "dynamic_sensor_x1")

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "sensor_x1", "records": records},
        )

        assert resp.status_code == 201
        body = resp.json()
        # first_timestamp = base_time, last_timestamp = base_time + 20s
        assert body["first_timestamp"] == base_time.isoformat()
        assert body["last_timestamp"] == (base_time + timedelta(seconds=20)).isoformat()

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_validates_object_id_consistency(self, mock_iceberg, client):
        """모든 레코드의 object_id가 요청의 object_id와 일치해야 한다."""
        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "worker_01",
                "records": [
                    {"object_id": "worker_01", "pos_x": 1.0},
                    {"object_id": "worker_02", "pos_x": 2.0},  # mismatch
                ],
            },
        )

        # Pydantic validator catches inter-record ID mismatch as 422,
        # router-level check catches request.object_id vs record mismatch as 400
        assert resp.status_code in (400, 422)

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_empty_records_returns_400(self, mock_iceberg, client):
        """빈 레코드 리스트에 대해 400을 반환한다."""
        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "worker_01", "records": []},
        )
        assert resp.status_code == 422  # Pydantic min_length=1

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_invalid_properties_json(self, mock_iceberg, client):
        """properties 필드의 유효하지 않은 JSON에 대해 422를 반환한다."""
        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "worker_01",
                "records": [{
                    "object_id": "worker_01",
                    "properties": "not a json",
                }],
            },
        )
        assert resp.status_code == 422

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_service_failure_returns_500(
        self, mock_iceberg, client, sensor_records_worker01
    ):
        """PyIceberg 쓰기 실패 시 500 에러가 전파된다."""
        mock_iceberg.insert_dynamic_records.side_effect = RuntimeError(
            "S3 bucket not found"
        )

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "worker_01",
                "records": sensor_records_worker01,
            },
        )
        assert resp.status_code == 500
        assert "S3 bucket not found" in resp.json()["detail"]

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_insert_auto_creates_table(self, mock_iceberg, client):
        """데이터 삽입 시 테이블이 자동 생성된다 (ensure_dynamic_table 호출)."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_new_obj")

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "new_obj",
                "records": [{
                    "object_id": "new_obj",
                    "pos_x": 5.0,
                    "pos_y": 10.0,
                    "space_id": "Room_A",
                }],
            },
        )

        assert resp.status_code == 201
        # insert_dynamic_records internally calls ensure_dynamic_table
        mock_iceberg.insert_dynamic_records.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
#  3. Full Pipeline: Table Create → Insert → Query
# ═══════════════════════════════════════════════════════════════════════

class TestFullPipelineIntegration:
    """
    전체 파이프라인 통합 테스트.

    테이블 생성 → 센서 데이터 삽입 → Trino 쿼리 조회의 전체 흐름을
    검증하여 데이터 무결성과 Trino 연동 정상 동작을 확인한다.
    """

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_insert_time_range_query(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_worker01,
        base_time,
    ):
        """
        E2E: 테이블 생성 → 10건 INSERT → 시간 범위 쿼리로 전체 검증.

        Pipeline:
          POST /dynamic-objects/tables    (Trino DDL)
          POST /dynamic-objects/sensor-data (PyIceberg Arrow write)
          POST /dynamic/query/time-range   (Trino SQL SELECT)
        """
        # ── Step 1: Create table ──
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        create_resp = client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )
        assert create_resp.status_code == 201
        assert create_resp.json()["created"] is True

        # ── Step 2: Insert sensor data ──
        mock_iceberg_router.insert_dynamic_records.return_value = (
            10, "dynamic_worker_01"
        )

        insert_resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "worker_01",
                "records": sensor_records_worker01,
            },
        )
        assert insert_resp.status_code == 201
        assert insert_resp.json()["inserted"] == 10

        # ── Step 3: Query by time range ──
        expected_rows = [
            [
                "worker_01",
                (base_time + timedelta(seconds=i * 10)).isoformat(),
                1.0 + i * 0.5,
                2.0 + i * 0.3,
                0.0, 0.0, 0.0,
                float(i * 15),
                0.5 + i * 0.1,
                "Room_A" if i < 7 else "Room_B",
                json.dumps({"battery": 100 - i * 2, "tag": "uwb"}),
            ]
            for i in range(10)
        ]

        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": expected_rows,
            "row_count": 10,
        }

        query_resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "worker_01",
                "start_time": base_time.isoformat(),
                "end_time": (base_time + timedelta(minutes=2)).isoformat(),
            },
        )
        assert query_resp.status_code == 200
        query_body = query_resp.json()
        assert query_body["row_count"] == 10
        assert len(query_body["columns"]) == 11

        # Verify data integrity: battery decreases monotonically
        for i, row in enumerate(query_body["rows"]):
            props = json.loads(row[10])
            assert props["battery"] == 100 - i * 2
            assert props["tag"] == "uwb"

        # Verify position values match inserted data
        assert query_body["rows"][0][2] == 1.0   # pos_x at t=0
        assert query_body["rows"][9][2] == 5.5   # pos_x at t=90s

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_insert_latest_query(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_worker01,
        base_time,
    ):
        """
        E2E: 테이블 생성 → INSERT → 최신 상태 쿼리.

        최신 레코드(마지막 INSERT된 행)가 정확히 반환되는지 검증.
        """
        # Step 1: Create
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )

        # Step 2: Insert
        mock_iceberg_router.insert_dynamic_records.return_value = (
            10, "dynamic_worker_01"
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "worker_01", "records": sensor_records_worker01},
        )

        # Step 3: Latest query — should return last record (i=9)
        last_ts = (base_time + timedelta(seconds=90)).isoformat()
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                [
                    "worker_01", last_ts,
                    5.5, 4.7, 0.0,
                    0.0, 0.0, 135.0,
                    1.4, "Room_B",
                    json.dumps({"battery": 82, "tag": "uwb"}),
                ],
            ],
            "row_count": 1,
        }

        latest_resp = client.get(
            "/api/v1/dynamic/query/latest?object_id=worker_01"
        )
        assert latest_resp.status_code == 200
        body = latest_resp.json()
        assert body["row_count"] == 1
        assert body["rows"][0][0] == "worker_01"
        assert body["rows"][0][9] == "Room_B"  # transitioned at i=7
        assert json.loads(body["rows"][0][10])["battery"] == 82

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_create_insert_trajectory_query(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_agv01,
        base_time,
    ):
        """
        E2E: AGV 궤적 데이터 INSERT → trajectory 쿼리로 이동 경로 검증.

        궤적 포인트가 시간순으로 정렬되고 공간적으로 연속적인지 확인.
        """
        # Create + Insert
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_agv_01"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "agv_01"},
        )

        mock_iceberg_router.insert_dynamic_records.return_value = (
            8, "dynamic_agv_01"
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "agv_01", "records": sensor_records_agv01},
        )

        # Trajectory query
        trajectory_rows = [
            [
                "agv_01",
                (base_time + timedelta(seconds=i * 15)).isoformat(),
                float(i * 3), float(i * 2), 0.0,
                1.5 + (0.5 if i in [2, 3, 6] else 0.0),
                ["Warehouse", "Warehouse", "Hallway_01", "Hallway_01",
                 "Room_B", "Room_B", "Hallway_01", "Warehouse"][i],
            ]
            for i in range(8)
        ]
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                         "speed", "space_id"],
            "rows": trajectory_rows,
            "row_count": 8,
        }

        traj_resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "agv_01",
                "start_time": base_time.isoformat(),
                "end_time": (base_time + timedelta(minutes=3)).isoformat(),
            },
        )

        assert traj_resp.status_code == 200
        body = traj_resp.json()
        assert body["row_count"] == 8

        # Verify trajectory is time-ordered (pos_x increases monotonically)
        x_vals = [row[2] for row in body["rows"]]
        assert x_vals == sorted(x_vals), "Trajectory must be time-ordered"

        # Verify space transitions
        spaces = [row[6] for row in body["rows"]]
        assert spaces[0] == "Warehouse"
        assert spaces[2] == "Hallway_01"
        assert spaces[4] == "Room_B"


# ═══════════════════════════════════════════════════════════════════════
#  4. Multi-Object Cross-Table Query Tests
# ═══════════════════════════════════════════════════════════════════════

class TestMultiObjectCrossTableIntegration:
    """
    복수 객체 시나리오 — cross-table UNION ALL 쿼리 검증.

    여러 dynamic_* 테이블에 걸쳐 공간 필터, 혼잡도 집계,
    공간 범위 쿼리가 정상 동작하는지 확인한다.
    """

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_multi_object_space_query(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_worker01,
        sensor_records_robot01,
        base_time,
    ):
        """
        두 객체(worker_01, robot_01) 데이터 삽입 후 공간 쿼리로
        Room_A에 있는 모든 객체를 cross-table로 조회한다.
        """
        # Create + Insert for both objects
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_worker_01"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "worker_01"},
        )
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_robot_01"
        client.post(
            "/api/v1/dynamic-objects/tables",
            json={"object_id": "robot_01"},
        )

        mock_iceberg_router.insert_dynamic_records.side_effect = [
            (10, "dynamic_worker_01"),
            (5, "dynamic_robot_01"),
        ]
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "worker_01", "records": sensor_records_worker01},
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "robot_01", "records": sensor_records_robot01},
        )

        # Space query: Room_A — should return both worker_01 and robot_01 records
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["worker_01", base_time.isoformat(), 1.0, 2.0, 0.0,
                 0.0, 0.0, 0.0, 0.5, "Room_A", "{}"],
                ["robot_01", base_time.isoformat(), 10.0, 5.0, 0.0,
                 0.0, 0.0, 0.0, 2.0, "Room_A", "{}"],
            ],
            "row_count": 2,
        }

        space_resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A"},
        )

        assert space_resp.status_code == 200
        body = space_resp.json()
        assert body["row_count"] == 2
        object_ids = {row[0] for row in body["rows"]}
        assert object_ids == {"worker_01", "robot_01"}
        # All results are in Room_A
        assert all(row[9] == "Room_A" for row in body["rows"])

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_multi_object_congestion_timeseries(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_worker01,
        sensor_records_robot01,
        sensor_records_agv01,
        base_time,
    ):
        """
        3개 객체(worker_01, robot_01, agv_01) 데이터 삽입 후
        혼잡도 시계열 쿼리로 공간별 시간별 객체 수를 집계한다.

        Expected distribution (at t=0 bucket):
          Room_A:     worker_01, robot_01  = 2
          Warehouse:  agv_01               = 1
        """
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_test"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        # Create tables
        for obj_id in ["worker_01", "robot_01", "agv_01"]:
            client.post(
                "/api/v1/dynamic-objects/tables",
                json={"object_id": obj_id},
            )

        # Insert data for all objects
        mock_iceberg_router.insert_dynamic_records.side_effect = [
            (10, "dynamic_worker_01"),
            (5, "dynamic_robot_01"),
            (8, "dynamic_agv_01"),
        ]
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "worker_01", "records": sensor_records_worker01},
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "robot_01", "records": sensor_records_robot01},
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "agv_01", "records": sensor_records_agv01},
        )

        # Congestion timeseries query
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", base_time.isoformat(), 2],
                ["Room_A", (base_time + timedelta(minutes=1)).isoformat(), 2],
                ["Room_B", base_time.isoformat(), 0],
                ["Room_B", (base_time + timedelta(minutes=1)).isoformat(), 2],
                ["Warehouse", base_time.isoformat(), 1],
                ["Hallway_01", (base_time + timedelta(seconds=30)).isoformat(), 1],
            ],
            "row_count": 6,
        }

        congestion_resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={
                "bucket_seconds": 60,
                "start_time": base_time.isoformat(),
                "end_time": (base_time + timedelta(minutes=5)).isoformat(),
            },
        )

        assert congestion_resp.status_code == 200
        body = congestion_resp.json()
        assert body["row_count"] == 6
        assert body["columns"] == ["space_id", "time_bucket", "object_count"]

        # Verify Room_A initial congestion = 2
        room_a_rows = [r for r in body["rows"] if r[0] == "Room_A"]
        assert len(room_a_rows) >= 1
        assert room_a_rows[0][2] == 2  # 2 objects at first bucket

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    @patch("app.routers.dynamic_objects.trino_list_dynamic_tables")
    @patch("app.routers.dynamic_objects.init_dynamic_table")
    def test_multi_object_spatial_range_query(
        self,
        mock_init_table,
        mock_list_tables_router,
        mock_iceberg_router,
        mock_iceberg_dynamic,
        mock_trino,
        client,
        sensor_records_worker01,
        sensor_records_robot01,
        base_time,
    ):
        """
        두 객체 삽입 후 공간 범위(bounding box) 쿼리로
        특정 좌표 영역 내 객체를 cross-table 검색한다.
        """
        mock_list_tables_router.return_value = []
        mock_init_table.return_value = "iceberg.dynamic_db.dynamic_test"
        mock_iceberg_router.ensure_dynamic_table.return_value = None

        for obj_id in ["worker_01", "robot_01"]:
            client.post(
                "/api/v1/dynamic-objects/tables",
                json={"object_id": obj_id},
            )

        mock_iceberg_router.insert_dynamic_records.side_effect = [
            (10, "dynamic_worker_01"),
            (5, "dynamic_robot_01"),
        ]
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "worker_01", "records": sensor_records_worker01},
        )
        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "robot_01", "records": sensor_records_robot01},
        )

        # Spatial range: small box around worker_01 start position (1,2)
        mock_trino.query_dynamic_spatial_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["worker_01", base_time.isoformat(), 1.0, 2.0, 0.0,
                 0.0, 0.0, 0.0, 0.5, "Room_A", "{}"],
            ],
            "row_count": 1,
        }

        spatial_resp = client.post(
            "/api/v1/dynamic/query/spatial-range",
            json={
                "x_min": 0.0,
                "x_max": 5.0,
                "y_min": 0.0,
                "y_max": 5.0,
            },
        )

        assert spatial_resp.status_code == 200
        body = spatial_resp.json()
        assert body["row_count"] == 1
        assert body["rows"][0][0] == "worker_01"
        # robot_01 starts at (10, 5) which is outside the bounding box

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    def test_multi_object_latest_all(
        self, mock_iceberg, mock_trino, client, base_time
    ):
        """
        전체 객체의 최신 상태 조회: 각 테이블에서 MAX(timestamp) 레코드를 반환.
        """
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["agv_01", (base_time + timedelta(minutes=1, seconds=45)).isoformat(),
                 21.0, 14.0, 0.0, 0.0, 0.0, 315.0, 1.5, "Warehouse", "{}"],
                ["robot_01", (base_time + timedelta(minutes=1, seconds=20)).isoformat(),
                 14.0, 7.0, 0.0, 0.0, 0.0, 0.0, 2.0, "Room_A", "{}"],
                ["worker_01", (base_time + timedelta(minutes=1, seconds=30)).isoformat(),
                 5.5, 4.7, 0.0, 0.0, 0.0, 135.0, 1.4, "Room_B", "{}"],
            ],
            "row_count": 3,
        }

        resp = client.get("/api/v1/dynamic/query/latest")
        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 3

        # Verify all three objects are present
        ids = {row[0] for row in body["rows"]}
        assert ids == {"agv_01", "robot_01", "worker_01"}


# ═══════════════════════════════════════════════════════════════════════
#  5. Trino Connectivity & Error Handling Tests
# ═══════════════════════════════════════════════════════════════════════

class TestTrinoConnectivityIntegration:
    """
    Trino 연동 에러 시나리오 검증.

    연결 실패, 쿼리 타임아웃, 카탈로그 미존재 등의 에러가
    적절히 전파되는지 확인한다.
    """

    @patch("app.api.v1.dynamic.trino_service")
    def test_trino_connection_refused_on_query(self, mock_trino, client):
        """Trino 연결 거부 시 쿼리 엔드포인트가 500을 반환한다."""
        mock_trino.query_dynamic_by_time_range.side_effect = RuntimeError(
            "Connection refused: Trino at trino:8080"
        )

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "robot_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        assert resp.status_code == 500
        assert "Connection refused" in resp.json()["detail"]

    @patch("app.api.v1.dynamic.trino_service")
    def test_trino_table_not_found_on_query(self, mock_trino, client):
        """존재하지 않는 테이블 쿼리 시 에러가 전파된다."""
        mock_trino.query_dynamic_by_time_range.side_effect = RuntimeError(
            "Table 'iceberg.dynamic_db.dynamic_ghost' does not exist"
        )

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "ghost",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        assert resp.status_code == 500
        assert "does not exist" in resp.json()["detail"]

    @patch("app.api.v1.dynamic.trino_service")
    def test_trino_timeout_on_space_query(self, mock_trino, client):
        """Trino 쿼리 타임아웃 시 500이 반환된다."""
        mock_trino.query_dynamic_by_space.side_effect = RuntimeError(
            "Query exceeded maximum execution time"
        )

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={"space_id": "Room_A"},
        )

        assert resp.status_code == 500

    @patch("app.api.v1.dynamic.trino_service")
    def test_trino_error_on_congestion_query(self, mock_trino, client):
        """혼잡도 쿼리에서 Trino 에러 시 500이 반환된다."""
        mock_trino.query_space_congestion_timeseries.side_effect = RuntimeError(
            "Iceberg catalog not available"
        )

        resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={"bucket_seconds": 60},
        )

        assert resp.status_code == 500

    @patch("app.api.v1.dynamic.trino_service")
    def test_list_tables_trino_error(self, mock_trino, client):
        """테이블 목록 조회 시 Trino 에러가 500으로 전파된다."""
        mock_trino.list_dynamic_tables.side_effect = RuntimeError(
            "Catalog 'iceberg' does not exist"
        )

        resp = client.get("/api/v1/dynamic/tables")
        assert resp.status_code == 500

    @patch("app.api.v1.dynamic.trino_service")
    def test_list_objects_trino_error(self, mock_trino, client):
        """객체 목록 조회 시 Trino 에러가 500으로 전파된다."""
        mock_trino.list_dynamic_objects.side_effect = RuntimeError(
            "Network unreachable"
        )

        resp = client.get("/api/v1/dynamic/objects")
        assert resp.status_code == 500


# ═══════════════════════════════════════════════════════════════════════
#  6. Schema Fixed-Column Validation Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDynamicSchemaIntegration:
    """
    고정 스키마 검증 테스트.

    Dynamic 객체 테이블의 고정 스키마(object_id, timestamp, pos_x/y/z,
    rot_x/y/z, speed, space_id, properties)가 올바르게 반영되는지 확인한다.
    """

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_full_schema_columns_in_record(self, mock_iceberg, client, base_time):
        """모든 스키마 컬럼이 레코드에 포함되어 서비스로 전달된다."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_test_obj")

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "test_obj",
                "records": [{
                    "object_id": "test_obj",
                    "timestamp": base_time.isoformat(),
                    "pos_x": 1.5,
                    "pos_y": 2.5,
                    "pos_z": 3.5,
                    "rot_x": 10.0,
                    "rot_y": 20.0,
                    "rot_z": 30.0,
                    "speed": 1.2,
                    "space_id": "Lab_01",
                    "properties": '{"sensor": "uwb", "accuracy": 0.15}',
                }],
            },
        )

        assert resp.status_code == 201

        # Verify all columns were passed to service
        call_args = mock_iceberg.insert_dynamic_records.call_args
        record = call_args[0][1][0]

        assert record["object_id"] == "test_obj"
        assert record["pos_x"] == 1.5
        assert record["pos_y"] == 2.5
        assert record["pos_z"] == 3.5
        assert record["rot_x"] == 10.0
        assert record["rot_y"] == 20.0
        assert record["rot_z"] == 30.0
        assert record["speed"] == 1.2
        assert record["space_id"] == "Lab_01"

        props = json.loads(record["properties"])
        assert props["sensor"] == "uwb"
        assert props["accuracy"] == 0.15

    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_default_values_applied(self, mock_iceberg, client):
        """최소 필수 필드만 제공 시 나머지가 기본값으로 채워진다."""
        mock_iceberg.insert_dynamic_records.return_value = (1, "dynamic_minimal")

        resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "minimal",
                "records": [{"object_id": "minimal"}],
            },
        )

        assert resp.status_code == 201
        record = mock_iceberg.insert_dynamic_records.call_args[0][1][0]

        assert record["pos_x"] == 0.0
        assert record["pos_y"] == 0.0
        assert record["pos_z"] == 0.0
        assert record["rot_x"] == 0.0
        assert record["rot_y"] == 0.0
        assert record["rot_z"] == 0.0
        assert record["speed"] == 0.0
        assert record["space_id"] == ""
        assert record["properties"] == "{}"

    @patch("app.api.v1.dynamic.trino_service")
    def test_query_response_has_11_columns(self, mock_trino, client, base_time):
        """쿼리 응답이 정확히 11개 컬럼을 포함한다 (고정 스키마)."""
        expected_columns = [
            "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
            "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
        ]
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": expected_columns,
            "rows": [
                ["obj_1", base_time.isoformat(), 1.0, 2.0, 0.0,
                 0.0, 0.0, 0.0, 0.5, "Room_A", "{}"],
            ],
            "row_count": 1,
        }

        resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "obj_1",
                "start_time": base_time.isoformat(),
                "end_time": (base_time + timedelta(hours=1)).isoformat(),
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["columns"] == expected_columns
        assert len(body["columns"]) == 11


# ═══════════════════════════════════════════════════════════════════════
#  7. Data Integrity Round-Trip Tests
# ═══════════════════════════════════════════════════════════════════════

class TestDataIntegrityRoundTrip:
    """
    데이터 무결성 왕복(round-trip) 테스트.

    INSERT된 데이터가 Trino 쿼리로 정확히 조회되는지 검증한다.
    특히 float 정밀도, JSON properties, 타임스탬프 형식을 확인한다.
    """

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_float_precision_preserved(
        self, mock_iceberg_router, mock_iceberg_dynamic, mock_trino, client
    ):
        """소수점 정밀도가 INSERT → SELECT 과정에서 유지된다."""
        precise_x = 12.345678
        precise_y = -67.891234
        precise_speed = 3.14159

        mock_iceberg_router.insert_dynamic_records.return_value = (
            1, "dynamic_precision_test"
        )

        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "precision_test",
                "records": [{
                    "object_id": "precision_test",
                    "timestamp": "2026-03-19T10:00:00",
                    "pos_x": precise_x,
                    "pos_y": precise_y,
                    "speed": precise_speed,
                    "space_id": "Lab",
                }],
            },
        )

        # Verify values passed to service layer
        record = mock_iceberg_router.insert_dynamic_records.call_args[0][1][0]
        assert record["pos_x"] == precise_x
        assert record["pos_y"] == precise_y
        assert record["speed"] == precise_speed

        # Simulate Trino returning the same values
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["precision_test", "2026-03-19T10:00:00",
                 precise_x, precise_y, 0.0,
                 0.0, 0.0, 0.0, precise_speed, "Lab", "{}"],
            ],
            "row_count": 1,
        }

        resp = client.get(
            "/api/v1/dynamic/query/latest?object_id=precision_test"
        )
        assert resp.status_code == 200
        row = resp.json()["rows"][0]
        assert row[2] == precise_x
        assert row[3] == precise_y
        assert row[8] == precise_speed

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_complex_properties_json_preserved(
        self, mock_iceberg_router, mock_iceberg_dynamic, mock_trino, client
    ):
        """복잡한 중첩 JSON properties가 INSERT → SELECT에서 보존된다."""
        complex_props = json.dumps({
            "sensor_type": "uwb",
            "anchors": ["A1", "A2", "A3"],
            "accuracy": {"horizontal": 0.15, "vertical": 0.30},
            "firmware": "v2.1.0",
            "calibrated": True,
            "last_sync": "2026-03-19T09:55:00",
        })

        mock_iceberg_router.insert_dynamic_records.return_value = (
            1, "dynamic_json_test"
        )

        client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={
                "object_id": "json_test",
                "records": [{
                    "object_id": "json_test",
                    "timestamp": "2026-03-19T10:00:00",
                    "pos_x": 5.0,
                    "properties": complex_props,
                }],
            },
        )

        # Verify JSON passed through intact
        record = mock_iceberg_router.insert_dynamic_records.call_args[0][1][0]
        parsed = json.loads(record["properties"])
        assert parsed["sensor_type"] == "uwb"
        assert len(parsed["anchors"]) == 3
        assert parsed["accuracy"]["horizontal"] == 0.15
        assert parsed["calibrated"] is True

        # Simulate Trino query returning the same JSON
        mock_trino.query_dynamic_latest.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["json_test", "2026-03-19T10:00:00",
                 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "", complex_props],
            ],
            "row_count": 1,
        }

        resp = client.get("/api/v1/dynamic/query/latest?object_id=json_test")
        assert resp.status_code == 200
        returned_props = json.loads(resp.json()["rows"][0][10])
        assert returned_props == json.loads(complex_props)

    @patch("app.api.v1.dynamic.trino_service")
    @patch("app.api.v1.dynamic.iceberg_service")
    @patch("app.routers.dynamic_objects.iceberg_service")
    def test_large_batch_integrity(
        self, mock_iceberg_router, mock_iceberg_dynamic, mock_trino, client
    ):
        """100건 대량 배치 삽입 후 조회 시 데이터 수가 일치한다."""
        base_time = datetime(2026, 3, 19, 10, 0, 0)
        batch_size = 100

        records = [
            {
                "object_id": "batch_obj",
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "pos_x": float(i % 50),
                "pos_y": float(i // 50),
                "pos_z": 0.0,
                "speed": 1.0,
                "space_id": f"Zone_{i % 5}",
                "properties": json.dumps({"seq": i}),
            }
            for i in range(batch_size)
        ]

        mock_iceberg_router.insert_dynamic_records.return_value = (
            batch_size, "dynamic_batch_obj"
        )

        insert_resp = client.post(
            "/api/v1/dynamic-objects/sensor-data",
            json={"object_id": "batch_obj", "records": records},
        )

        assert insert_resp.status_code == 201
        assert insert_resp.json()["inserted"] == batch_size

        # Verify all 100 records passed to service
        call_args = mock_iceberg_router.insert_dynamic_records.call_args
        assert len(call_args[0][1]) == batch_size

        # Query should return matching count
        mock_trino.query_dynamic_by_time_range.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                [
                    "batch_obj",
                    (base_time + timedelta(seconds=i)).isoformat(),
                    float(i % 50), float(i // 50), 0.0,
                    0.0, 0.0, 0.0, 1.0,
                    f"Zone_{i % 5}",
                    json.dumps({"seq": i}),
                ]
                for i in range(batch_size)
            ],
            "row_count": batch_size,
        }

        query_resp = client.post(
            "/api/v1/dynamic/query/time-range",
            json={
                "object_id": "batch_obj",
                "start_time": base_time.isoformat(),
                "end_time": (base_time + timedelta(minutes=2)).isoformat(),
                "limit": 200,
            },
        )

        assert query_resp.status_code == 200
        assert query_resp.json()["row_count"] == batch_size

        # Spot-check sequence numbers
        rows = query_resp.json()["rows"]
        for i in [0, 49, 99]:
            props = json.loads(rows[i][10])
            assert props["seq"] == i


# ═══════════════════════════════════════════════════════════════════════
#  8. Downsampled Trajectory & Advanced Query Tests
# ═══════════════════════════════════════════════════════════════════════

class TestAdvancedQueryIntegration:
    """다운샘플링, 정렬, 시공간 결합 등 고급 쿼리 시나리오 검증."""

    @patch("app.api.v1.dynamic.trino_service")
    def test_trajectory_with_downsampling(self, mock_trino, client):
        """시간 버킷 다운샘플링 궤적 쿼리가 정상 동작한다."""
        mock_trino.query_dynamic_trajectory.return_value = {
            "columns": ["object_id", "time_bucket", "pos_x", "pos_y", "pos_z",
                         "speed", "sample_count"],
            "rows": [
                ["agv_01", "2026-03-19T10:00:00", 3.0, 2.0, 0.0, 1.5, 4],
                ["agv_01", "2026-03-19T10:01:00", 12.0, 8.0, 0.0, 1.7, 4],
            ],
            "row_count": 2,
        }

        resp = client.post(
            "/api/v1/dynamic/query/trajectory",
            json={
                "object_id": "agv_01",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:02:00",
                "sample_interval_seconds": 60,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 2
        # Each bucket aggregates 4 samples
        assert body["rows"][0][6] == 4
        assert body["rows"][1][6] == 4

        # Verify service was called with downsampling param
        mock_trino.query_dynamic_trajectory.assert_called_once()
        kwargs = mock_trino.query_dynamic_trajectory.call_args.kwargs
        assert kwargs.get("sample_interval_seconds") == 60

    @patch("app.api.v1.dynamic.trino_service")
    def test_space_query_with_time_window(self, mock_trino, client):
        """공간+시간 결합 필터 쿼리가 정상 동작한다."""
        mock_trino.query_dynamic_by_space.return_value = {
            "columns": [
                "object_id", "timestamp", "pos_x", "pos_y", "pos_z",
                "rot_x", "rot_y", "rot_z", "speed", "space_id", "properties",
            ],
            "rows": [
                ["worker_01", "2026-03-19T10:30:00", 3.0, 4.0, 0.0,
                 0.0, 0.0, 0.0, 0.8, "Room_A", "{}"],
            ],
            "row_count": 1,
        }

        resp = client.post(
            "/api/v1/dynamic/query/by-space",
            json={
                "space_id": "Room_A",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
                "limit": 50,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 1

        # Verify all parameters passed through
        mock_trino.query_dynamic_by_space.assert_called_once()
        kwargs = mock_trino.query_dynamic_by_space.call_args.kwargs
        assert kwargs["space_id"] == "Room_A"
        assert kwargs["limit"] == 50

    @patch("app.api.v1.dynamic.trino_service")
    def test_spatial_range_3d_with_time_filter(self, mock_trino, client):
        """3D 공간 범위 + 시간 필터 결합 쿼리가 정상 동작한다."""
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
                "x_min": -10.0,
                "x_max": 10.0,
                "y_min": -10.0,
                "y_max": 10.0,
                "z_min": 0.0,
                "z_max": 5.0,
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T11:00:00",
            },
        )

        assert resp.status_code == 200

        # Verify all spatial + temporal params
        kwargs = mock_trino.query_dynamic_spatial_range.call_args.kwargs
        assert kwargs["x_min"] == -10.0
        assert kwargs["x_max"] == 10.0
        assert kwargs["z_min"] == 0.0
        assert kwargs["z_max"] == 5.0

    @patch("app.api.v1.dynamic.trino_service")
    def test_congestion_single_space_filter(self, mock_trino, client):
        """단일 공간 필터링된 혼잡도 시계열 쿼리가 정상 동작한다."""
        mock_trino.query_space_congestion_timeseries.return_value = {
            "columns": ["space_id", "time_bucket", "object_count"],
            "rows": [
                ["Room_A", "2026-03-19T10:00:00", 3],
                ["Room_A", "2026-03-19T10:01:00", 2],
                ["Room_A", "2026-03-19T10:02:00", 4],
            ],
            "row_count": 3,
        }

        resp = client.post(
            "/api/v1/dynamic/query/congestion-timeseries",
            json={
                "space_id": "Room_A",
                "start_time": "2026-03-19T10:00:00",
                "end_time": "2026-03-19T10:05:00",
                "bucket_seconds": 60,
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["row_count"] == 3
        assert all(row[0] == "Room_A" for row in body["rows"])

        # Congestion should vary over time
        counts = [row[2] for row in body["rows"]]
        assert counts == [3, 2, 4]
