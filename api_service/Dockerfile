# =============================================================================
# Lakehouse API Middleware — FastAPI service for Iceberg Lakehouse + OpenUSD
# Bridges NVIDIA Isaac Sim Extensions ↔ Iceberg data layer (Polaris + MinIO)
#
# Build context : api_service/
#   - Root docker-compose  : context: ./api_service
#   - Iceberg docker-compose: context: ../../api_service
# Container port : 8000  →  Host port: 8100 (mapped by docker-compose)
#
# Multi-stage build:
#   builder  — installs Python dependencies in an isolated layer
#   runtime  — lean production image; copies only site-packages + app code
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — compile / install all Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Prevent .pyc files and enable real-time log output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Keep pip quiet during build; no progress bar clutter in CI logs
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build-time system packages needed to compile C-extension wheels
# (gcc + libffi-dev cover pyiceberg / cryptography native modules)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only the dependency manifest first so Docker can cache this layer
# independently of application source changes.
COPY requirements.txt .

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime — lean production image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# OCI / Docker image labels (useful for scanning, registries, research docs)
LABEL org.opencontainers.image.title="NetAI-Digital-Twin Lakehouse API" \
      org.opencontainers.image.description="FastAPI middleware bridging NVIDIA Isaac Sim to an Apache Iceberg Lakehouse (Polaris + MinIO + Trino)" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="NetAI Lab" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Runtime OS packages:
#   curl — used by the HEALTHCHECK probe
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# ── Copy installed site-packages and CLI entry-points from builder ──────────
COPY --from=builder /usr/local/lib/python3.11/site-packages \
                    /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin \
                    /usr/local/bin

# ── Create a non-root user for security best-practice ───────────────────────
# Omniverse / Isaac Sim also runs as non-root; aligning here avoids permission
# issues when bind-mounting USD asset directories in future iterations.
RUN groupadd --gid 1001 appgroup && \
    useradd  --uid 1001 --gid appgroup --no-create-home --shell /bin/false appuser

WORKDIR /app

# Copy application source (tests/ and other dev artefacts excluded via .dockerignore)
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# FastAPI/uvicorn listens on this port inside the container
EXPOSE 8000

# ── Health-check ─────────────────────────────────────────────────────────────
# Docker / orchestrators poll this to decide whether the container is "healthy".
# The /health endpoint returns JSON with full dependency status (MinIO, Polaris,
# Trino); a non-200 response or timeout marks the container unhealthy.
HEALTHCHECK --interval=30s \
            --timeout=5s \
            --start-period=20s \
            --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Container entry-point ────────────────────────────────────────────────────
# uvicorn serves the ASGI app on all interfaces (0.0.0.0) so that the
# Docker bridge network can forward traffic from the host / other containers.
#
# workers=1 is intentional for a single-container deployment; scale
# horizontally via docker-compose replicas when needed.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
