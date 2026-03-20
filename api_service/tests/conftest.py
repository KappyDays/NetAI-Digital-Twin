"""Shared pytest fixtures for Lakehouse API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    """Return a FastAPI TestClient for integration tests."""
    return TestClient(app)
