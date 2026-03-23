"""Lakehouse API — FastAPI middleware for Iceberg Lakehouse / OpenUSD data management.

This service bridges NVIDIA Isaac Sim extensions to the Iceberg Lakehouse,
providing endpoints for Static/Dynamic object management, USD file uploads,
and spatio-temporal congestion queries.

Endpoints:
    GET  /health                  — Health check (with dependency status)
    GET  /api/v1/health           — Lightweight health check
    POST /api/v1/prims            — Insert static Prim records (legacy compat)
    POST /api/v1/static/prims     — Insert static Prim records (Iceberg)
    POST /api/v1/dynamic/ingest   — Ingest dynamic object IoT data (Iceberg)
    POST /api/v1/upload-usd       — Upload USD files (S3/MinIO)
    POST /api/v1/query            — Ad-hoc Trino SQL query
    GET  /api/v1/congestion       — Space congestion aggregation

Run: uvicorn app.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import logger
from app.core.trino_config import bootstrap_schema, check_iceberg_catalog

# ---------------------------------------------------------------------------
# Startup / shutdown lifecycle
# ---------------------------------------------------------------------------
_start_time: float = time.time()
_bootstrap_result: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler — bootstraps Iceberg schema on startup."""
    global _bootstrap_result
    try:
        _bootstrap_result = bootstrap_schema()
        if _bootstrap_result.get("status") == "ok":
            logger.info(
                "Iceberg schema bootstrap OK: %s",
                _bootstrap_result.get("static_table"),
            )
        else:
            logger.warning("Iceberg schema bootstrap issue: %s", _bootstrap_result)
    except Exception as exc:
        logger.error("Iceberg schema bootstrap failed: %s", exc)
        _bootstrap_result = {"status": "error", "message": str(exc)}
    yield
    # Shutdown: nothing to clean up for now


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Lakehouse API",
    description=(
        "REST API middleware that bridges NVIDIA Isaac Sim (Omniverse) "
        "to an Apache Iceberg Lakehouse (Polaris + MinIO + Trino). "
        "Manages Static/Dynamic USD object data and provides "
        "spatiotemporal congestion visualization endpoints."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS — allow Isaac Sim extension (urllib) and web dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Mount v1 API routes
# ---------------------------------------------------------------------------
app.include_router(api_router)

# NOTE: POST /api/v1/prims is now served by app.api.v1.prims router
# (included via api_router), replacing the previous legacy shim.


# ---------------------------------------------------------------------------
# Helper: check MinIO connectivity
# ---------------------------------------------------------------------------
def _check_minio() -> dict:
    """Return MinIO health status dict."""
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        s3.list_buckets()
        return {"status": "healthy", "endpoint": settings.s3_endpoint}
    except (ClientError, EndpointConnectionError, Exception) as exc:
        return {"status": "unhealthy", "error": str(exc)}


# ---------------------------------------------------------------------------
# Helper: check Polaris connectivity
# ---------------------------------------------------------------------------
def _check_polaris() -> dict:
    """Return Polaris catalog health status dict."""
    try:
        import urllib.request

        # Polaris 1.3.0 uses Quarkus management interface on port 8182
        polaris_base = settings.iceberg_catalog_uri.replace("/api/catalog", "")
        health_url = polaris_base.replace(":8181", ":8182") + "/q/health"
        req = urllib.request.Request(health_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return {"status": "healthy", "endpoint": settings.iceberg_catalog_uri}
            return {"status": "unhealthy", "http_status": resp.status}
    except Exception as exc:
        return {"status": "unhealthy", "error": str(exc)}


# ---------------------------------------------------------------------------
# /health  — Deep Health Check Endpoint (with dependencies)
# ---------------------------------------------------------------------------
@app.get("/health", tags=["System"])
def health_check():
    """Return service health with dependency connectivity status.

    This endpoint is used by:
    - Docker HEALTHCHECK
    - Isaac Sim extension connectivity probes
    - Monitoring / observability stacks

    Returns:
        JSON with overall status, uptime, and per-dependency health.
    """
    uptime_seconds = round(time.time() - _start_time, 2)
    now = datetime.now(timezone.utc).isoformat()

    minio_health = _check_minio()
    polaris_health = _check_polaris()

    # Trino / Iceberg catalog check
    try:
        trino_health = check_iceberg_catalog()
        trino_health["status"] = (
            "healthy" if trino_health.get("status") == "ok" else "unhealthy"
        )
    except Exception as exc:
        trino_health = {"status": "unhealthy", "error": str(exc)}

    # Overall status: healthy only if all dependencies are healthy
    deps = [minio_health, polaris_health, trino_health]
    overall = "healthy" if all(d["status"] == "healthy" for d in deps) else "degraded"

    return {
        "status": overall,
        "service": "lakehouse-api",
        "version": app.version,
        "timestamp": now,
        "uptime_seconds": uptime_seconds,
        "dependencies": {
            "minio": minio_health,
            "polaris": polaris_health,
            "trino_iceberg": trino_health,
        },
        "bootstrap": _bootstrap_result,
    }


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------
@app.get("/", tags=["System"])
def root():
    """Root endpoint — quick service info."""
    return {
        "service": "lakehouse-api",
        "version": app.version,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
