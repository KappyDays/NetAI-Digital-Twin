"""
Trino SQL query execution service.

Used for:
  - Ad-hoc queries on Iceberg tables
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.logging import logger
from app.core.trino_config import create_trino_connection


# ═══════════════════════════════════════════════════════════════════════
#  Connection
# ═══════════════════════════════════════════════════════════════════════

def get_trino_connection():
    """Create and return a Trino connection via centralized trino_config."""
    return create_trino_connection()


# ═══════════════════════════════════════════════════════════════════════
#  Generic query execution
# ═══════════════════════════════════════════════════════════════════════

def execute_query(sql: str) -> dict:
    """Execute a read-only SQL query via Trino and return results."""
    conn = get_trino_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        logger.info("Trino query returned %d rows", len(rows))
        return {
            "columns": columns,
            "rows": _serialize_rows(rows),
            "row_count": len(rows),
        }
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════
#  Serialization helpers
# ═══════════════════════════════════════════════════════════════════════

def _serialize_value(val: Any) -> Any:
    """Convert a single value to a JSON-safe type."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, Decimal):
        return float(val) if val != val.to_integral_value() else int(val)
    if isinstance(val, dict):
        return {str(k): _serialize_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]
    if isinstance(val, (str, int, float, bool)):
        return val
    return str(val)


def _serialize_rows(rows: list) -> list[list[Any]]:
    """Ensure all row values are JSON-serializable."""
    return [[_serialize_value(val) for val in row] for row in rows]
