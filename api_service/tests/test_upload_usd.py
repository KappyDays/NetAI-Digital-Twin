"""Tests for POST /api/v1/upload-usd endpoint.

Verifies USD file upload to MinIO/S3 via the FastAPI middleware.
Uses unittest.mock to stub out the boto3 S3 client so tests run
without a live MinIO instance.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_usd_bytes(size: int = 128) -> bytes:
    """Return dummy bytes representing a USD file."""
    return b"\x00" * size


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUploadUsd:
    """POST /api/v1/upload-usd test suite."""

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_success(self, mock_get_client, client):
        """A valid USD file upload returns 200 with correct metadata."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        content = _make_usd_bytes()
        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("test_scene.usd", io.BytesIO(content), "application/octet-stream")},
            data={"prim_path": "/World/Room_01"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "test_scene.usd"
        assert "s3_key" in body
        assert body["s3_key"].endswith("test_scene.usd")
        assert "bucket" in body
        assert body.get("message", "ok") == "ok"

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_usda_extension(self, mock_get_client, client):
        """USDA (ASCII) files are also accepted."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        content = b'#usda 1.0\ndef Xform "World" {}\n'
        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("scene.usda", io.BytesIO(content), "application/octet-stream")},
            data={"prim_path": ""},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["filename"] == "scene.usda"

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_usdc_extension(self, mock_get_client, client):
        """USDC (binary/crate) files are also accepted."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("binary.usdc", io.BytesIO(_make_usd_bytes(256)), "application/octet-stream")},
        )

        assert resp.status_code == 200
        assert resp.json()["filename"] == "binary.usdc"

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_s3_key_has_prefix(self, mock_get_client, client):
        """The returned s3_key includes the configured prefix path."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("room.usd", io.BytesIO(_make_usd_bytes()), "application/octet-stream")},
        )

        assert resp.status_code == 200
        s3_key = resp.json()["s3_key"]
        # Default prefix from config is "usd/world_prims/"
        assert s3_key.startswith("usd/world_prims/")

    def test_upload_usd_no_file_returns_422(self, client):
        """Missing file field returns 422 validation error."""
        resp = client.post("/api/v1/upload-usd")
        assert resp.status_code == 422

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_s3_failure_returns_500(self, mock_get_client, client):
        """If S3 upload fails, the endpoint returns 500."""
        mock_s3 = MagicMock()
        mock_s3.upload_fileobj.side_effect = Exception("Connection refused")
        mock_get_client.return_value = mock_s3

        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("fail.usd", io.BytesIO(_make_usd_bytes()), "application/octet-stream")},
        )

        assert resp.status_code == 500
        assert "Connection refused" in resp.json()["detail"]

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_prim_path_optional(self, mock_get_client, client):
        """prim_path form field is optional (defaults to empty string)."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("no_prim.usd", io.BytesIO(_make_usd_bytes()), "application/octet-stream")},
            # No prim_path provided
        )

        assert resp.status_code == 200
        assert resp.json()["filename"] == "no_prim.usd"

    @patch("app.services.s3_service.get_s3_client")
    def test_upload_usd_large_file(self, mock_get_client, client):
        """Larger files (simulating real USD scenes) are handled correctly."""
        mock_s3 = MagicMock()
        mock_get_client.return_value = mock_s3

        # 1MB dummy file
        content = _make_usd_bytes(1024 * 1024)
        resp = client.post(
            "/api/v1/upload-usd",
            files={"file": ("large_scene.usd", io.BytesIO(content), "application/octet-stream")},
            data={"prim_path": "/World"},
        )

        assert resp.status_code == 200
        assert resp.json()["filename"] == "large_scene.usd"
