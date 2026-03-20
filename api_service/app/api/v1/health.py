"""Health check endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.models.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Returns API server status – used by Isaac Sim extension for connectivity test."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        version="1.0.0",
    )
