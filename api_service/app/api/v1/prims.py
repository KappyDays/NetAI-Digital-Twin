"""
POST /api/v1/prims — Static Prim ingestion endpoint.

This is the primary endpoint called by Isaac Sim extensions to push
USD stage Prim data into the Iceberg Lakehouse.  It validates the
incoming batch, delegates to iceberg_service for Iceberg table writes,
and returns a structured success/error response.

Space derivation logic:
    prim_path = "/World/Room_A/Chair_01"  →  space_id = "Room_A"
    Only paths rooted at /World with at least two segments yield a space_id.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.core.logging import logger
from app.models.schemas import PrimInsertRequest, PrimInsertResponse, PrimRecord
from app.services import iceberg_service

router = APIRouter(tags=["Static Objects"])

# Regex for a valid USD Prim path: must start with / and contain valid identifiers
_PRIM_PATH_RE = re.compile(r"^/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*$")

# Maximum batch size to prevent memory exhaustion
_MAX_BATCH_SIZE = 50_000


def _validate_prim_path(path: str) -> str | None:
    """Return an error message if *path* is not a valid USD prim path, else None."""
    if not path:
        return "prim_path must not be empty"
    if not path.startswith("/"):
        return f"prim_path must start with '/': {path}"
    if not _PRIM_PATH_RE.match(path):
        return f"prim_path contains invalid characters: {path}"
    return None


def _validate_properties_json(props: str) -> str | None:
    """Return an error message if *props* is not valid JSON, else None."""
    try:
        json.loads(props)
    except (json.JSONDecodeError, TypeError) as exc:
        return f"properties must be valid JSON: {exc}"
    return None


@router.post("/prims", response_model=PrimInsertResponse)
async def insert_prims(request: PrimInsertRequest) -> PrimInsertResponse:
    """Batch-insert static Prim records into the Iceberg Lakehouse.

    **Request body** (``PrimInsertRequest``):
    ```json
    {
      "records": [
        {
          "prim_path": "/World/Room_A/Chair_01",
          "type": "Mesh",
          "properties": "{\"material\": \"wood\"}"
        }
      ]
    }
    ```

    **Validation rules**:
    - ``records`` list must not be empty and must not exceed 50 000 items.
    - Each ``prim_path`` must be a valid USD path (``/Segment/Segment/...``).
    - Each ``properties`` field must be a valid JSON string.

    **Returns** ``PrimInsertResponse`` on success or raises 400/500.
    """

    # ── 1. Empty batch check ─────────────────────────────────────────
    if not request.records:
        raise HTTPException(
            status_code=400,
            detail="No records provided — 'records' list must not be empty.",
        )

    # ── 2. Batch size guard ──────────────────────────────────────────
    if len(request.records) > _MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Batch too large: {len(request.records)} records "
                f"(max {_MAX_BATCH_SIZE}). Split into smaller batches."
            ),
        )

    # ── 3. Per-record validation ─────────────────────────────────────
    errors: list[dict[str, Any]] = []
    for idx, record in enumerate(request.records):
        path_err = _validate_prim_path(record.prim_path)
        if path_err:
            errors.append({"index": idx, "field": "prim_path", "error": path_err})

        props_err = _validate_properties_json(record.properties)
        if props_err:
            errors.append({"index": idx, "field": "properties", "error": props_err})

    if errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Validation failed for {len(errors)} field(s)",
                "errors": errors[:50],  # cap error list to avoid huge payloads
            },
        )

    # ── 4. Iceberg write ─────────────────────────────────────────────
    try:
        records_dicts = [r.model_dump(by_alias=True) for r in request.records]
        count = iceberg_service.insert_static_prims(records_dicts)
    except Exception as exc:
        logger.error("Failed to insert static prims via Iceberg: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Iceberg write failed: {exc}",
        )

    # ── 5. Success response ──────────────────────────────────────────
    table_fqn = (
        f"{iceberg_service.settings.iceberg_namespace}"
        f".{iceberg_service.settings.iceberg_table_name}"
    )
    logger.info(
        "POST /api/v1/prims — inserted %d records into %s",
        count,
        table_fqn,
    )
    return PrimInsertResponse(
        inserted=count,
        table=table_fqn,
        message=f"Successfully inserted {count} static prim records",
    )
