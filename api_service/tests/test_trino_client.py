"""
Tests for the Trino client module (trino_client.py).

Covers:
  - TrinoClient initialisation and configuration
  - Connection pool checkout / return / exhaustion
  - Query helpers (execute_query, fetch_all, fetch_one, fetch_scalar)
  - Health check (is_healthy / wait_until_ready)
  - Row serialisation (_serialize_rows)
  - Context managers (connection / cursor)
  - Pool stats and close
"""

from __future__ import annotations

import threading
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.core.trino_client import (
    TrinoClient,
    _ConnectionPool,
    _serialize_rows,
)


# ═══════════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════════


def _make_mock_connection(alive: bool = True, select_result: list | None = None):
    """Create a mock Trino DBAPI connection."""
    conn = MagicMock()
    cursor = MagicMock()

    if select_result is not None:
        cursor.fetchall.return_value = select_result
        cursor.fetchone.return_value = select_result[0] if select_result else None
    else:
        cursor.fetchall.return_value = [(1,)]
        cursor.fetchone.return_value = (1,)

    cursor.description = [("col1", None, None, None, None, None, None)]
    conn.cursor.return_value = cursor
    return conn


@pytest.fixture()
def mock_trino_connect():
    """Patch trino.dbapi.connect to return mock connections."""
    with patch("app.core.trino_client.trino.dbapi.connect") as mock_connect:
        mock_connect.return_value = _make_mock_connection()
        yield mock_connect


@pytest.fixture()
def client_instance(mock_trino_connect):
    """Create a TrinoClient with mocked connections."""
    c = TrinoClient(
        host="test-host",
        port=9999,
        user="test-user",
        catalog="test-catalog",
        schema="test-schema",
        pool_size=3,
        pool_timeout=2.0,
    )
    yield c
    c.close()


# ═══════════════════════════════════════════════════════════════════════
#  Configuration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTrinoClientInit:
    """TrinoClient initialisation and configuration."""

    def test_default_settings(self, mock_trino_connect):
        """Client uses settings defaults when no params given."""
        from app.core.config import settings

        c = TrinoClient()
        assert c.host == settings.trino_host
        assert c.port == settings.trino_port
        assert c.user == settings.trino_user
        assert c.catalog == settings.trino_catalog
        assert c.schema == settings.iceberg_namespace
        c.close()

    def test_custom_settings(self, mock_trino_connect):
        """Client respects explicit constructor params."""
        c = TrinoClient(
            host="custom-host",
            port=1234,
            user="custom-user",
            catalog="custom-cat",
            schema="custom-schema",
            pool_size=10,
        )
        assert c.host == "custom-host"
        assert c.port == 1234
        assert c.user == "custom-user"
        assert c.catalog == "custom-cat"
        assert c.schema == "custom-schema"
        assert c.pool._max_size == 10
        c.close()

    def test_repr(self, client_instance):
        """__repr__ includes host, port, catalog info."""
        r = repr(client_instance)
        assert "test-host" in r
        assert "9999" in r
        assert "test-catalog" in r


# ═══════════════════════════════════════════════════════════════════════
#  Connection Pool Tests
# ═══════════════════════════════════════════════════════════════════════


class TestConnectionPool:
    """_ConnectionPool thread-safe connection management."""

    def test_get_creates_connection(self, mock_trino_connect):
        """get() creates a connection when pool is empty."""
        pool = _ConnectionPool(
            host="h", port=1, user="u", catalog="c", schema="s", max_size=2,
        )
        conn = pool.get()
        assert conn is not None
        assert pool.size == 1

    def test_put_returns_to_pool(self, mock_trino_connect):
        """put() makes the connection available for reuse."""
        pool = _ConnectionPool(
            host="h", port=1, user="u", catalog="c", schema="s", max_size=2,
        )
        conn = pool.get()
        assert pool.idle == 0
        pool.put(conn)
        assert pool.idle == 1

    def test_close_all_drains_pool(self, mock_trino_connect):
        """close_all() closes all idle connections."""
        pool = _ConnectionPool(
            host="h", port=1, user="u", catalog="c", schema="s", max_size=3,
        )
        conns = [pool.get() for _ in range(3)]
        for c in conns:
            pool.put(c)
        assert pool.idle == 3
        pool.close_all()
        assert pool.idle == 0

    def test_pool_repr(self, mock_trino_connect):
        """__repr__ shows pool state."""
        pool = _ConnectionPool(
            host="h", port=1, user="u", catalog="c", schema="s", max_size=2,
        )
        r = repr(pool)
        assert "host=h" in r
        assert "catalog=c" in r


# ═══════════════════════════════════════════════════════════════════════
#  Query Helper Tests
# ═══════════════════════════════════════════════════════════════════════


class TestQueryHelpers:
    """Query execution helper methods."""

    def test_execute_query(self, client_instance, mock_trino_connect):
        """execute_query returns structured dict with columns/rows/row_count."""
        result = client_instance.execute_query("SELECT 1 AS ping")
        assert "columns" in result
        assert "rows" in result
        assert "row_count" in result
        assert result["row_count"] == 1

    def test_fetch_all(self, client_instance, mock_trino_connect):
        """fetch_all returns raw list of tuples."""
        rows = client_instance.fetch_all("SELECT 1")
        assert isinstance(rows, list)
        assert rows == [(1,)]

    def test_fetch_one(self, client_instance, mock_trino_connect):
        """fetch_one returns a single tuple."""
        row = client_instance.fetch_one("SELECT 1")
        assert row == (1,)

    def test_fetch_one_empty(self, client_instance, mock_trino_connect):
        """fetch_one returns None when result is empty."""
        # Configure mock to return None for fetchone
        mock_conn = _make_mock_connection()
        mock_conn.cursor().fetchone.return_value = None
        mock_trino_connect.return_value = mock_conn

        row = client_instance.fetch_one("SELECT 1 WHERE FALSE")
        assert row is None

    def test_fetch_scalar(self, client_instance, mock_trino_connect):
        """fetch_scalar returns the first column of the first row."""
        result = client_instance.fetch_scalar("SELECT 42")
        assert result == 1  # first column of (1,) from the mock default

    def test_fetch_scalar_empty(self, client_instance, mock_trino_connect):
        """fetch_scalar returns None when result is empty."""
        mock_conn = _make_mock_connection()
        mock_conn.cursor().fetchone.return_value = None
        mock_trino_connect.return_value = mock_conn

        result = client_instance.fetch_scalar("SELECT 1 WHERE FALSE")
        assert result is None

    def test_execute_ddl(self, client_instance, mock_trino_connect):
        """execute() runs DDL without returning results."""
        # Should not raise
        client_instance.execute("CREATE TABLE IF NOT EXISTS test (id INT)")


# ═══════════════════════════════════════════════════════════════════════
#  Context Manager Tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextManagers:
    """connection() and cursor() context managers."""

    def test_connection_context(self, client_instance, mock_trino_connect):
        """connection() yields a usable connection."""
        with client_instance.connection() as conn:
            assert conn is not None

    def test_cursor_context(self, client_instance, mock_trino_connect):
        """cursor() yields a usable cursor."""
        with client_instance.cursor() as cur:
            cur.execute("SELECT 1")
            rows = cur.fetchall()
            assert rows == [(1,)]

    def test_cursor_with_override(self, client_instance, mock_trino_connect):
        """cursor() accepts catalog/schema overrides."""
        with client_instance.cursor(catalog="other_cat", schema="other_schema") as cur:
            cur.execute("SELECT 1")
            # Verify trino.dbapi.connect was called with overrides
            calls = mock_trino_connect.call_args_list
            # The last call should have the override
            last_call = calls[-1]
            assert last_call.kwargs.get("catalog") == "other_cat" or \
                   last_call[1].get("catalog") == "other_cat"


# ═══════════════════════════════════════════════════════════════════════
#  Health Check Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHealthChecks:
    """is_healthy and wait_until_ready methods."""

    def test_is_healthy_success(self, mock_trino_connect):
        """is_healthy returns True when Trino responds to SELECT 1."""
        mock_conn = _make_mock_connection()
        mock_conn.cursor().fetchone.return_value = (1,)
        mock_trino_connect.return_value = mock_conn

        c = TrinoClient(host="h", port=1, user="u", catalog="c", schema="s")
        assert c.is_healthy() is True
        c.close()

    def test_is_healthy_failure(self, mock_trino_connect):
        """is_healthy returns False when Trino is unreachable."""
        mock_trino_connect.side_effect = Exception("Connection refused")

        c = TrinoClient(host="h", port=1, user="u", catalog="c", schema="s")
        assert c.is_healthy() is False
        c.close()

    def test_wait_until_ready_immediate(self, mock_trino_connect):
        """wait_until_ready returns True immediately if Trino is up."""
        c = TrinoClient(host="h", port=1, user="u", catalog="c", schema="s")
        assert c.wait_until_ready(max_retries=1) is True
        c.close()

    def test_wait_until_ready_failure(self, mock_trino_connect):
        """wait_until_ready returns False after exhausting retries."""
        mock_trino_connect.side_effect = Exception("Connection refused")

        c = TrinoClient(host="h", port=1, user="u", catalog="c", schema="s")
        assert c.wait_until_ready(max_retries=1, retry_interval=0.01) is False
        c.close()


# ═══════════════════════════════════════════════════════════════════════
#  Pool Stats Tests
# ═══════════════════════════════════════════════════════════════════════


class TestPoolStats:
    """get_pool_stats diagnostics."""

    def test_pool_stats(self, client_instance):
        """get_pool_stats returns expected keys."""
        stats = client_instance.get_pool_stats()
        assert stats["host"] == "test-host"
        assert stats["port"] == 9999
        assert stats["catalog"] == "test-catalog"
        assert stats["schema"] == "test-schema"
        assert stats["pool_size"] == 3
        assert "connections_created" in stats
        assert "connections_idle" in stats


# ═══════════════════════════════════════════════════════════════════════
#  Serialisation Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSerializeRows:
    """_serialize_rows utility function."""

    def test_basic_types(self):
        """Integers, strings, floats pass through unchanged."""
        rows = [(1, "hello", 3.14)]
        result = _serialize_rows(rows)
        assert result == [[1, "hello", 3.14]]

    def test_datetime_conversion(self):
        """datetime objects are converted to ISO-8601 strings."""
        dt = datetime(2025, 1, 15, 10, 30, 0)
        rows = [(dt,)]
        result = _serialize_rows(rows)
        assert result == [["2025-01-15T10:30:00"]]

    def test_bytes_conversion(self):
        """bytes are decoded to UTF-8 strings."""
        rows = [(b"binary_data",)]
        result = _serialize_rows(rows)
        assert result == [["binary_data"]]

    def test_none_passthrough(self):
        """None values pass through as None."""
        rows = [(None,)]
        result = _serialize_rows(rows)
        assert result == [[None]]

    def test_empty_rows(self):
        """Empty input returns empty output."""
        assert _serialize_rows([]) == []

    def test_mixed_types(self):
        """Mixed types in a single row are handled correctly."""
        dt = datetime(2025, 6, 1, 12, 0, 0)
        rows = [(1, "text", dt, None, 3.14, b"data")]
        result = _serialize_rows(rows)
        assert result == [[1, "text", "2025-06-01T12:00:00", None, 3.14, "data"]]


# ═══════════════════════════════════════════════════════════════════════
#  Module-level singleton
# ═══════════════════════════════════════════════════════════════════════


class TestSingleton:
    """Module-level trino_client singleton."""

    def test_singleton_exists(self):
        """The module exports a trino_client singleton."""
        from app.core.trino_client import trino_client
        assert trino_client is not None
        assert isinstance(trino_client, TrinoClient)

    def test_singleton_uses_settings(self):
        """The singleton reads config from settings."""
        from app.core.config import settings
        from app.core.trino_client import trino_client

        assert trino_client.host == settings.trino_host
        assert trino_client.port == settings.trino_port
        assert trino_client.catalog == settings.trino_catalog
