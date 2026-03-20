"""
Trino client module with connection pooling and query execution helpers.

Provides a thread-safe, reusable TrinoClient class that centralises all
Trino interactions for the Lakehouse API middleware:

  1. **Connection pooling** — maintains a bounded pool of DBAPI connections
     so that concurrent API requests share connections instead of creating
     a new TCP socket per query.
  2. **Query helpers** — typed wrappers for common operations (execute,
     fetch_one, fetch_all, fetch_scalar, execute_many) with automatic
     connection checkout / return and serialisation of result rows.
  3. **Retry & health** — configurable retry on transient errors and an
     ``is_healthy()`` probe used by the /health endpoint.
  4. **Configuration** — reads Trino host / port / catalog / schema from
     the centralised ``Settings`` object (env-driven via docker-compose).

Architecture note
-----------------
This module is the **single entry-point** that higher-level services
(``trino_service.py``, ``trino_config.py``, route handlers) should use
for raw Trino SQL execution. It does NOT contain table DDL or domain
logic — those belong in ``trino_config.py`` (schema bootstrap) and
``trino_service.py`` (query composition).

Usage
-----
    from app.core.trino_client import trino_client

    # Simple query
    result = trino_client.execute_query("SELECT 1 AS ping")
    # result == {"columns": ["ping"], "rows": [[1]], "row_count": 1}

    # Context-managed cursor for multi-statement work
    with trino_client.cursor() as cur:
        cur.execute("SHOW SCHEMAS FROM iceberg")
        schemas = [r[0] for r in cur.fetchall()]
"""

from __future__ import annotations

import queue
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

import trino
from trino.dbapi import Connection

from app.core.config import settings
from app.core.logging import logger


# ═══════════════════════════════════════════════════════════════════════
#  Connection Pool
# ═══════════════════════════════════════════════════════════════════════

class _ConnectionPool:
    """
    Thread-safe bounded connection pool for Trino DBAPI connections.

    Design decisions:
      - Uses ``queue.Queue`` (thread-safe FIFO) to store idle connections.
      - Connections are lazily created up to ``max_size``.
      - A checked-out connection is validated with a fast ``SELECT 1``
        before being handed to the caller (stale detection).
      - If the pool is exhausted, ``get()`` blocks for up to ``timeout``
        seconds before raising ``TimeoutError``.

    Parameters
    ----------
    host : str
        Trino coordinator hostname.
    port : int
        Trino coordinator HTTP port.
    user : str
        Trino user identity.
    catalog : str
        Default Trino catalog (e.g. ``iceberg``).
    schema : str
        Default schema/namespace (e.g. ``static_db``).
    max_size : int
        Maximum number of pooled connections (default 5).
    timeout : float
        Seconds to wait for a free connection when pool is full (default 30).
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        catalog: str,
        schema: str,
        max_size: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._catalog = catalog
        self._schema = schema
        self._max_size = max_size
        self._timeout = timeout

        # Idle-connection FIFO
        self._pool: queue.Queue[Connection] = queue.Queue(maxsize=max_size)
        # Track how many connections have been created (incl. checked-out)
        self._created = 0
        self._lock = threading.Lock()

    # ── Internal helpers ──────────────────────────────────────────────

    def _make_connection(
        self,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Connection:
        """Create a fresh Trino DBAPI connection."""
        return trino.dbapi.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            catalog=catalog or self._catalog,
            schema=schema or self._schema,
            http_scheme="http",
        )

    def _is_alive(self, conn: Connection) -> bool:
        """Validate a connection with a lightweight probe."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchall()
            cur.close()
            return True
        except Exception:
            return False

    # ── Public API ────────────────────────────────────────────────────

    def get(
        self,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Connection:
        """
        Checkout a connection from the pool.

        If an idle connection is available, validate and return it.
        If the pool hasn't reached ``max_size``, create a new one.
        Otherwise, block up to ``timeout`` seconds.

        Parameters
        ----------
        catalog : str, optional
            Override catalog for this connection.
        schema : str, optional
            Override schema for this connection.

        Returns
        -------
        Connection
            A validated Trino DBAPI connection.

        Raises
        ------
        TimeoutError
            If no connection becomes available within the timeout.
        """
        use_custom = catalog or schema

        # 1. Try to grab an idle connection
        try:
            conn = self._pool.get_nowait()
            if use_custom:
                # Custom catalog/schema requested — can't reuse pooled conn
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created -= 1
            elif self._is_alive(conn):
                return conn
            else:
                # Dead connection — discard and create fresh
                with self._lock:
                    self._created -= 1
        except queue.Empty:
            pass

        # 2. Create a new connection if below capacity
        with self._lock:
            if self._created < self._max_size:
                self._created += 1
                try:
                    return self._make_connection(catalog=catalog, schema=schema)
                except Exception:
                    self._created -= 1
                    raise

        # 3. Wait for a returned connection
        try:
            conn = self._pool.get(timeout=self._timeout)
            if use_custom:
                try:
                    conn.close()
                except Exception:
                    pass
                with self._lock:
                    self._created -= 1
                    self._created += 1
                return self._make_connection(catalog=catalog, schema=schema)
            if self._is_alive(conn):
                return conn
            # Stale — replace
            with self._lock:
                self._created -= 1
                self._created += 1
            return self._make_connection()
        except queue.Empty:
            raise TimeoutError(
                f"Trino connection pool exhausted (max_size={self._max_size}, "
                f"timeout={self._timeout}s)"
            )

    def put(self, conn: Connection) -> None:
        """
        Return a connection to the pool.

        If the pool is full the connection is silently closed instead of
        being returned, preventing unbounded growth.
        """
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._created -= 1

    def close_all(self) -> None:
        """Drain and close every idle connection in the pool."""
        closed = 0
        while True:
            try:
                conn = self._pool.get_nowait()
                try:
                    conn.close()
                except Exception:
                    pass
                closed += 1
            except queue.Empty:
                break
        with self._lock:
            self._created -= closed
            if self._created < 0:
                self._created = 0
        logger.info("Closed %d pooled Trino connections", closed)

    @property
    def size(self) -> int:
        """Number of connections currently created (idle + in-use)."""
        return self._created

    @property
    def idle(self) -> int:
        """Number of idle connections waiting in the pool."""
        return self._pool.qsize()

    def __repr__(self) -> str:
        return (
            f"<_ConnectionPool host={self._host}:{self._port} "
            f"catalog={self._catalog} schema={self._schema} "
            f"created={self._created} idle={self.idle}/{self._max_size}>"
        )


# ═══════════════════════════════════════════════════════════════════════
#  Trino Client
# ═══════════════════════════════════════════════════════════════════════

class TrinoClient:
    """
    High-level Trino query client with connection pooling.

    Wraps a ``_ConnectionPool`` and exposes ergonomic query helpers that
    automatically checkout, use, and return connections.

    Attributes
    ----------
    host : str
    port : int
    user : str
    catalog : str
    schema : str
    pool : _ConnectionPool

    Examples
    --------
    >>> client = TrinoClient()           # uses settings.*
    >>> client.fetch_scalar("SELECT 1")  # -> 1
    >>> client.execute_query("SHOW TABLES FROM iceberg.static_db")
    {"columns": ["Table"], "rows": [["static_prims"]], "row_count": 1}
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        catalog: str | None = None,
        schema: str | None = None,
        pool_size: int = 5,
        pool_timeout: float = 30.0,
    ) -> None:
        self.host = host or settings.trino_host
        self.port = port or settings.trino_port
        self.user = user or settings.trino_user
        self.catalog = catalog or settings.trino_catalog
        self.schema = schema or settings.iceberg_namespace

        self.pool = _ConnectionPool(
            host=self.host,
            port=self.port,
            user=self.user,
            catalog=self.catalog,
            schema=self.schema,
            max_size=pool_size,
            timeout=pool_timeout,
        )
        logger.info(
            "TrinoClient initialised: %s:%d catalog=%s schema=%s pool_size=%d",
            self.host, self.port, self.catalog, self.schema, pool_size,
        )

    # ── Connection context managers ───────────────────────────────────

    @contextmanager
    def connection(
        self,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Generator[Connection, None, None]:
        """
        Context-managed connection from the pool.

        The connection is automatically returned to the pool on exit.
        If an exception occurs, the connection is closed (not returned)
        to avoid returning a potentially dirty connection.

        Parameters
        ----------
        catalog : str, optional
            Override catalog for this connection.
        schema : str, optional
            Override schema for this connection.
        """
        conn = self.pool.get(catalog=catalog, schema=schema)
        try:
            yield conn
            # Only return to pool if no catalog/schema override
            if not catalog and not schema:
                self.pool.put(conn)
            else:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            # On error, close instead of returning to pool
            try:
                conn.close()
            except Exception:
                pass
            raise

    @contextmanager
    def cursor(
        self,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Generator[Any, None, None]:
        """
        Context-managed Trino cursor (connection + cursor).

        Usage::

            with trino_client.cursor() as cur:
                cur.execute("SHOW SCHEMAS FROM iceberg")
                rows = cur.fetchall()

        Parameters
        ----------
        catalog : str, optional
            Override catalog for this connection.
        schema : str, optional
            Override schema for this connection.
        """
        with self.connection(catalog=catalog, schema=schema) as conn:
            cur = conn.cursor()
            try:
                yield cur
            finally:
                cur.close()

    # ── Query execution helpers ───────────────────────────────────────

    def execute(
        self,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> None:
        """
        Execute a SQL statement that returns no result set (DDL, INSERT, etc.).

        Parameters
        ----------
        sql : str
            The SQL statement to execute.
        catalog : str, optional
            Override catalog for this query.
        schema : str, optional
            Override schema for this query.
        """
        with self.cursor(catalog=catalog, schema=schema) as cur:
            cur.execute(sql)
            cur.fetchall()  # consume result to ensure completion
        logger.debug("Executed SQL (no result): %.120s", sql)

    def execute_query(
        self,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> dict:
        """
        Execute a SQL query and return structured results.

        Returns
        -------
        dict
            ``{"columns": [...], "rows": [...], "row_count": int}``
            where rows are JSON-serialisable lists of lists.
        """
        with self.cursor(catalog=catalog, schema=schema) as cur:
            cur.execute(sql)
            columns = (
                [desc[0] for desc in cur.description] if cur.description else []
            )
            rows = cur.fetchall()

        serialised = _serialize_rows(rows)
        logger.info("Query returned %d rows: %.100s", len(rows), sql)
        return {
            "columns": columns,
            "rows": serialised,
            "row_count": len(rows),
        }

    def fetch_all(
        self,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> list[tuple]:
        """
        Execute a query and return raw rows as a list of tuples.

        Unlike ``execute_query`` this does NOT serialise datetime objects
        and does NOT wrap the result in a dict — useful for internal
        callers that process rows programmatically.
        """
        with self.cursor(catalog=catalog, schema=schema) as cur:
            cur.execute(sql)
            return cur.fetchall()

    def fetch_one(
        self,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Optional[tuple]:
        """
        Execute a query and return the first row (or ``None``).
        """
        with self.cursor(catalog=catalog, schema=schema) as cur:
            cur.execute(sql)
            return cur.fetchone()

    def fetch_scalar(
        self,
        sql: str,
        catalog: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """
        Execute a query and return the first column of the first row.

        Returns ``None`` if the result set is empty.

        Typical usage::

            count = trino_client.fetch_scalar("SELECT COUNT(*) FROM t")
        """
        row = self.fetch_one(sql, catalog=catalog, schema=schema)
        return row[0] if row else None

    # ── Health & diagnostics ──────────────────────────────────────────

    def is_healthy(self) -> bool:
        """
        Quick health probe: execute ``SELECT 1`` and verify the result.

        Returns ``True`` if Trino responded correctly, ``False`` otherwise.
        """
        try:
            result = self.fetch_scalar("SELECT 1")
            return result == 1
        except Exception as exc:
            logger.warning("Trino health check failed: %s", exc)
            return False

    def wait_until_ready(
        self,
        max_retries: int = 15,
        retry_interval: float = 4.0,
    ) -> bool:
        """
        Block until Trino is ready, retrying on failure.

        Parameters
        ----------
        max_retries : int
            Maximum number of attempts.
        retry_interval : float
            Seconds to wait between retries.

        Returns
        -------
        bool
            ``True`` if Trino became available, ``False`` if all
            retries were exhausted.
        """
        for attempt in range(1, max_retries + 1):
            try:
                conn = trino.dbapi.connect(
                    host=self.host,
                    port=self.port,
                    user=self.user,
                    http_scheme="http",
                )
                cur = conn.cursor()
                cur.execute("SELECT 1")
                cur.fetchall()
                cur.close()
                conn.close()
                logger.info(
                    "Trino ready (attempt %d/%d)", attempt, max_retries,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Trino not ready (attempt %d/%d): %s",
                    attempt, max_retries, str(exc)[:120],
                )
                time.sleep(retry_interval)

        logger.error(
            "Trino did not become ready after %d attempts", max_retries,
        )
        return False

    def get_pool_stats(self) -> dict:
        """
        Return pool statistics for monitoring / diagnostics.

        Returns
        -------
        dict
            Pool connection counts and configuration.
        """
        return {
            "host": self.host,
            "port": self.port,
            "catalog": self.catalog,
            "schema": self.schema,
            "pool_size": self.pool._max_size,
            "connections_created": self.pool.size,
            "connections_idle": self.pool.idle,
        }

    def close(self) -> None:
        """Close all pooled connections and release resources."""
        self.pool.close_all()
        logger.info("TrinoClient closed")

    def __repr__(self) -> str:
        return (
            f"<TrinoClient {self.host}:{self.port} "
            f"catalog={self.catalog} schema={self.schema} "
            f"pool={self.pool.size}/{self.pool._max_size}>"
        )


# ═══════════════════════════════════════════════════════════════════════
#  Serialisation Utility
# ═══════════════════════════════════════════════════════════════════════

def _serialize_rows(rows: list) -> list[list[Any]]:
    """
    Ensure all row values are JSON-serialisable.

    Converts:
      - ``datetime`` → ISO-8601 string
      - ``bytes``    → UTF-8 decoded string
    """
    result: list[list[Any]] = []
    for row in rows:
        serialised: list[Any] = []
        for val in row:
            if isinstance(val, datetime):
                serialised.append(val.isoformat())
            elif isinstance(val, bytes):
                serialised.append(val.decode("utf-8", errors="replace"))
            else:
                serialised.append(val)
        result.append(serialised)
    return result


# ═══════════════════════════════════════════════════════════════════════
#  Module-level singleton
# ═══════════════════════════════════════════════════════════════════════

#: Default TrinoClient instance — import this in other modules.
#:
#: Usage::
#:
#:     from app.core.trino_client import trino_client
#:     result = trino_client.execute_query("SELECT 1")
#:
trino_client = TrinoClient()
