"""Shared SQL utility functions for Trino query building."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException


def esc(val: str) -> str:
    """Escape single quotes for Trino SQL string literals."""
    if val is None:
        return ""
    return str(val).replace("'", "''")


def validate_timestamp(ts: str) -> str:
    """Validate and normalize a timestamp string to prevent SQL injection."""
    try:
        dt = datetime.fromisoformat(ts.replace(" ", "T").rstrip("Z"))
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid timestamp format")


def validate_table_id(val: str) -> str:
    """Validate a string is safe for use as a SQL table identifier."""
    safe = val.replace("-", "_").replace(" ", "_").lower()
    if not re.match(r"^[a-z0-9_]{1,128}$", safe):
        raise HTTPException(status_code=400, detail="Invalid identifier for table name")
    return safe
