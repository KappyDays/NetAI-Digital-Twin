"""
Trino–Iceberg connection configuration and schema bootstrap.

This module centralizes all Trino connection logic for the Lakehouse API:
  1. Connection factory with retry/health-check
  2. Iceberg catalog & namespace validation
  3. Schema initialization for Static/Dynamic tables

Architecture note:
  - Trino connects to the Iceberg REST catalog (Apache Polaris) which
    manages metadata.  MinIO provides the S3-compatible object store.
  - The Trino catalog name (`iceberg`) corresponds to the
    `iceberg.properties` file mounted at /etc/trino/catalog/.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

import trino
from trino.dbapi import Connection

from app.core.config import settings
from app.core.logging import logger

# ═══════════════════════════════════════════════════════════════════════
#  Connection Parameters
# ═══════════════════════════════════════════════════════════════════════

TRINO_CONN_PARAMS = {
    "host": settings.trino_host,
    "port": settings.trino_port,
    "user": settings.trino_user,
    "catalog": settings.trino_catalog,
    "schema": settings.iceberg_namespace,
    "http_scheme": "http",
}

# Maximum number of retries when waiting for Trino to become available
TRINO_MAX_RETRIES = 15
TRINO_RETRY_INTERVAL_SEC = 4


# ═══════════════════════════════════════════════════════════════════════
#  Connection Factory
# ═══════════════════════════════════════════════════════════════════════


def create_trino_connection(
    catalog: str | None = None,
    schema: str | None = None,
) -> Connection:
    """
    Create a Trino DBAPI connection.

    Parameters
    ----------
    catalog : str, optional
        Override the default Trino catalog (default: settings.trino_catalog).
    schema : str, optional
        Override the default schema/namespace (default: settings.iceberg_namespace).
    """
    params = dict(TRINO_CONN_PARAMS)
    if catalog:
        params["catalog"] = catalog
    if schema:
        params["schema"] = schema
    return trino.dbapi.connect(**params)


@contextmanager
def trino_connection(
    catalog: str | None = None,
    schema: str | None = None,
) -> Generator[Connection, None, None]:
    """Context-managed Trino connection that auto-closes."""
    conn = create_trino_connection(catalog=catalog, schema=schema)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def trino_cursor(
    catalog: str | None = None,
    schema: str | None = None,
):
    """Context-managed Trino cursor (connection + cursor)."""
    with trino_connection(catalog=catalog, schema=schema) as conn:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            cursor.close()


# ═══════════════════════════════════════════════════════════════════════
#  Health & Readiness
# ═══════════════════════════════════════════════════════════════════════


def wait_for_trino(max_retries: int = TRINO_MAX_RETRIES) -> bool:
    """
    Block until Trino is ready to accept queries.

    Returns True if Trino became available, False otherwise.
    """
    for attempt in range(1, max_retries + 1):
        try:
            conn = trino.dbapi.connect(
                host=settings.trino_host,
                port=settings.trino_port,
                user=settings.trino_user,
                http_scheme="http",
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()
            conn.close()
            logger.info("Trino is ready (attempt %d/%d)", attempt, max_retries)
            return True
        except Exception as exc:
            logger.warning(
                "Trino not ready (attempt %d/%d): %s",
                attempt,
                max_retries,
                str(exc)[:120],
            )
            time.sleep(TRINO_RETRY_INTERVAL_SEC)

    logger.error("Trino did not become ready after %d attempts", max_retries)
    return False


def check_iceberg_catalog() -> dict:
    """
    Verify that the Iceberg catalog is accessible through Trino.

    Returns a dict with catalog info and available schemas.
    """
    with trino_cursor(schema=None) as cursor:
        # Verify catalog exists
        cursor.execute("SHOW CATALOGS")
        catalogs = [row[0] for row in cursor.fetchall()]

        if settings.trino_catalog not in catalogs:
            return {
                "status": "error",
                "message": f"Catalog '{settings.trino_catalog}' not found",
                "available_catalogs": catalogs,
            }

        # List schemas in the Iceberg catalog
        cursor.execute(f"SHOW SCHEMAS FROM {settings.trino_catalog}")
        schemas = [row[0] for row in cursor.fetchall()]

        return {
            "status": "ok",
            "catalog": settings.trino_catalog,
            "schemas": schemas,
            "connection": {
                "host": settings.trino_host,
                "port": settings.trino_port,
                "user": settings.trino_user,
            },
        }


# ═══════════════════════════════════════════════════════════════════════
#  Schema Bootstrap (Namespace + Tables)
# ═══════════════════════════════════════════════════════════════════════

# SQL definitions for the Static prim table (static_prims)
# Partitioned by space_id for efficient per-space queries and overwrites.
STATIC_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} (
    prim_path   VARCHAR NOT NULL,
    type        VARCHAR NOT NULL,
    properties  VARCHAR,
    space_id    VARCHAR,
    ingested_at TIMESTAMP(6)
)
WITH (
    format = 'PARQUET',
    partitioning = ARRAY['space_id']
)
"""

# SQL definition template for per-object Dynamic tables
DYNAMIC_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {catalog}.{namespace}.{table} (
    object_id   VARCHAR NOT NULL,
    timestamp   TIMESTAMP(6) NOT NULL,
    pos_x       DOUBLE,
    pos_y       DOUBLE,
    pos_z       DOUBLE,
    rot_x       DOUBLE,
    rot_y       DOUBLE,
    rot_z       DOUBLE,
    speed       DOUBLE,
    space_id    VARCHAR,
    properties  VARCHAR
)
WITH (format = 'PARQUET')
"""


def init_namespace(namespace: str | None = None) -> str:
    """
    Create the Iceberg namespace (schema) in Trino if it doesn't exist.

    Returns the namespace name.
    """
    ns = namespace or settings.iceberg_namespace
    catalog = settings.trino_catalog
    with trino_cursor(schema=None) as cursor:
        cursor.execute(
            f"CREATE SCHEMA IF NOT EXISTS {catalog}.{ns}"
        )
        cursor.fetchall()  # consume result
        logger.info("Ensured namespace exists: %s.%s", catalog, ns)
    return ns


def init_static_table(
    namespace: str | None = None,
    table_name: str | None = None,
) -> str:
    """
    Bootstrap the static prim table in the Iceberg catalog via Trino.

    Returns the fully-qualified table name.
    """
    ns = namespace or settings.iceberg_namespace
    tbl = table_name or settings.iceberg_table_name
    catalog = settings.trino_catalog
    init_namespace(ns)

    ddl = STATIC_TABLE_DDL.format(catalog=catalog, namespace=ns, table=tbl)
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(ddl)
        cursor.fetchall()
        logger.info("Ensured static table: %s.%s.%s", catalog, ns, tbl)

    return f"{catalog}.{ns}.{tbl}"


def init_dynamic_table(
    object_id: str,
    namespace: str | None = None,
) -> str:
    """
    Bootstrap a per-object dynamic table in the Iceberg catalog via Trino.

    Table naming convention: dynamic_<sanitised_object_id>

    Returns the fully-qualified table name.
    """
    ns = namespace or settings.iceberg_namespace
    catalog = settings.trino_catalog
    safe_id = object_id.replace("-", "_").replace(" ", "_").lower()
    tbl = f"dynamic_{safe_id}"
    init_namespace(ns)

    ddl = DYNAMIC_TABLE_DDL.format(catalog=catalog, namespace=ns, table=tbl)
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(ddl)
        cursor.fetchall()
        logger.info("Ensured dynamic table: %s.%s.%s", catalog, ns, tbl)

    return f"{catalog}.{ns}.{tbl}"


def list_dynamic_tables(namespace: str | None = None) -> list[str]:
    """Return all dynamic_* table names in the given namespace."""
    ns = namespace or settings.iceberg_namespace
    catalog = settings.trino_catalog
    with trino_cursor(schema=ns) as cursor:
        cursor.execute(
            f"SHOW TABLES FROM {catalog}.{ns} LIKE 'dynamic_%'"
        )
        return [row[0] for row in cursor.fetchall()]


def bootstrap_schema() -> dict:
    """
    Full schema bootstrap: wait for Trino, create namespace and static table.

    Called once at API startup. Returns status dict.
    """
    if not wait_for_trino():
        return {"status": "error", "message": "Trino not available"}

    try:
        fq_table = init_static_table()
        catalog_info = check_iceberg_catalog()
        return {
            "status": "ok",
            "static_table": fq_table,
            "catalog_info": catalog_info,
        }
    except Exception as exc:
        logger.error("Schema bootstrap failed: %s", exc)
        return {"status": "error", "message": str(exc)}
