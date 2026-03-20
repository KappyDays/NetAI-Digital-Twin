"""Tests for POST /api/v1/prims endpoint — request validation and response."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


# ──────────────────────────────────────────────────────────────────────
#  Validation tests (no Iceberg/Trino dependency)
# ──────────────────────────────────────────────────────────────────────

def test_prims_empty_records(client):
    """400 when records list is empty."""
    resp = client.post("/api/v1/prims", json={"records": []})
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_prims_missing_records_field(client):
    """422 when required 'records' field is missing (Pydantic validation)."""
    resp = client.post("/api/v1/prims", json={})
    assert resp.status_code == 422


def test_prims_invalid_prim_path_no_leading_slash(client):
    """400 when prim_path does not start with '/'."""
    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "World/Room", "type": "Xform", "properties": "{}"}
        ],
    })
    assert resp.status_code == 400
    body = resp.json()["detail"]
    assert body["errors"][0]["field"] == "prim_path"


def test_prims_invalid_prim_path_special_chars(client):
    """400 when prim_path contains special characters."""
    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "/World/Room A!", "type": "Xform", "properties": "{}"}
        ],
    })
    assert resp.status_code == 400


def test_prims_invalid_properties_json(client):
    """400 when properties is not valid JSON."""
    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "/World/Room", "type": "Xform", "properties": "not-json"}
        ],
    })
    assert resp.status_code == 400
    body = resp.json()["detail"]
    assert any(e["field"] == "properties" for e in body["errors"])


def test_prims_batch_too_large(client):
    """400 when batch exceeds max size."""
    # We won't build 50001 records; just verify the guard works
    # by patching the constant
    from app.api.v1 import prims as prims_mod
    original = prims_mod._MAX_BATCH_SIZE
    prims_mod._MAX_BATCH_SIZE = 2
    try:
        resp = client.post("/api/v1/prims", json={
            "records": [
                {"prim_path": "/World/A", "type": "Xform", "properties": "{}"},
                {"prim_path": "/World/B", "type": "Xform", "properties": "{}"},
                {"prim_path": "/World/C", "type": "Xform", "properties": "{}"},
            ],
        })
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()
    finally:
        prims_mod._MAX_BATCH_SIZE = original


# ──────────────────────────────────────────────────────────────────────
#  Success path (Iceberg service mocked)
# ──────────────────────────────────────────────────────────────────────

@patch("app.api.v1.prims.iceberg_service")
def test_prims_insert_success(mock_iceberg, client):
    """200 with correct response when Iceberg write succeeds."""
    mock_iceberg.insert_static_prims.return_value = 2
    mock_iceberg.settings = MagicMock(
        iceberg_namespace="static_db",
        iceberg_table_name="table_a",
    )

    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "/World/Room_A/Chair_01", "type": "Mesh", "properties": "{}"},
            {"prim_path": "/World/Room_A/Table_01", "type": "Mesh", "properties": "{\"material\": \"wood\"}"},
        ],
    })

    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 2
    assert body["table"] == "static_db.table_a"
    assert "ok" in body["message"].lower() or "success" in body["message"].lower()
    mock_iceberg.insert_static_prims.assert_called_once()


# ──────────────────────────────────────────────────────────────────────
#  Error path (Iceberg service raises)
# ──────────────────────────────────────────────────────────────────────

@patch("app.api.v1.prims.iceberg_service")
def test_prims_insert_iceberg_failure(mock_iceberg, client):
    """500 when Iceberg write raises an exception."""
    mock_iceberg.insert_static_prims.side_effect = RuntimeError("Connection refused")

    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "/World/Room_A/Chair", "type": "Mesh", "properties": "{}"},
        ],
    })

    assert resp.status_code == 500
    assert "Connection refused" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────
#  Multiple validation errors
# ──────────────────────────────────────────────────────────────────────

def test_prims_multiple_validation_errors(client):
    """400 with multiple errors when several records have issues."""
    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "no_slash", "type": "Xform", "properties": "bad-json"},
            {"prim_path": "/World/OK", "type": "Mesh", "properties": "{}"},
        ],
    })
    assert resp.status_code == 400
    body = resp.json()["detail"]
    # Two errors: one for prim_path, one for properties
    assert len(body["errors"]) == 2


@patch("app.api.v1.prims.iceberg_service")
def test_prims_single_record_success(mock_iceberg, client):
    """200 with single record insert."""
    mock_iceberg.insert_static_prims.return_value = 1
    mock_iceberg.settings = MagicMock(
        iceberg_namespace="static_db",
        iceberg_table_name="table_a",
    )

    resp = client.post("/api/v1/prims", json={
        "records": [
            {"prim_path": "/World/Lab", "type": "Xform", "properties": "{}"},
        ],
    })

    assert resp.status_code == 200
    assert resp.json()["inserted"] == 1
