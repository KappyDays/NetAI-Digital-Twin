"""
Ad-hoc SQL query endpoint.

Provides read-only SQL query passthrough to Trino/Iceberg for
the Extension UI and web dashboard.
"""

from fastapi import APIRouter, HTTPException

from app.core.logging import logger
from app.models.schemas import QueryRequest, QueryResponse
from app.services import trino_service

router = APIRouter(tags=["Query"])


@router.post("/query", response_model=QueryResponse)
async def execute_query(request: QueryRequest):
    """
    Execute an ad-hoc SQL query via Trino on Iceberg tables.

    Use for custom data exploration and dashboard widgets.
    """
    sql = request.sql.strip().rstrip(";").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="Empty SQL query")

    tokens = sql.upper().split()
    first_keyword = tokens[0] if tokens else ""
    FORBIDDEN = {"INSERT", "UPDATE", "TRUNCATE", "GRANT", "REVOKE"}
    if first_keyword in FORBIDDEN:
        raise HTTPException(status_code=400, detail=f"'{first_keyword}' statements are not allowed through this endpoint")
    if first_keyword == "DROP" and not (len(tokens) >= 2 and tokens[1] == "TABLE"):
        raise HTTPException(status_code=400, detail="Only DROP TABLE is allowed; other DROP statements are blocked")

    try:
        result = trino_service.execute_query(sql)
        return QueryResponse(**result)
    except Exception as e:
        logger.error("Trino query failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
