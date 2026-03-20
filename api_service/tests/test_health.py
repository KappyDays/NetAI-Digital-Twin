"""Smoke tests for health and root endpoints."""

from __future__ import annotations


def test_root(client):
    """GET / returns service info."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "lakehouse-api"
    assert "version" in body


def test_v1_health(client):
    """GET /api/v1/health returns ok status."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
