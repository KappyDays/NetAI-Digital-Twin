#!/bin/bash
# =============================================================================
# Iceberg Lakehouse Stack — Start Script
# =============================================================================
# Initializes directories, validates .env, and starts all services.
#
# Usage:
#   ./start.sh           # Start with build
#   ./start.sh --verify  # Start + run health verification
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Verify .env exists ──────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found!"
    echo ""
    echo "Create one from the template:"
    echo "  cp example.env .env"
    echo "  # Edit .env with your credentials"
    echo ""
    exit 1
fi

# ── Validate critical env vars ──────────────────────────────────────────────
set -a
source .env
set +a

REQUIRED_VARS=(
    "MINIO_ROOT_USER"
    "MINIO_ROOT_PASSWORD"
    "AWS_ACCESS_KEY_ID"
    "AWS_SECRET_ACCESS_KEY"
    "POLARIS_ROOT_CLIENT_ID"
    "POLARIS_ROOT_CLIENT_SECRET"
    "USER_DATA_PATH"
    "ICEBERG_WAREHOUSE"
    "S3_BUCKET"
)

MISSING=0
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required variable '${var}' is not set in .env"
        MISSING=1
    fi
done

if [ "$MISSING" -eq 1 ]; then
    echo ""
    echo "Please set all required variables in .env (see example.env)"
    exit 1
fi

# Credential consistency check
if [ "$MINIO_ROOT_USER" != "$AWS_ACCESS_KEY_ID" ] || \
   [ "$MINIO_ROOT_PASSWORD" != "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "WARNING: MINIO_ROOT_USER/PASSWORD do not match AWS_ACCESS_KEY_ID/SECRET_ACCESS_KEY"
    echo "  This will cause Trino/Polaris to fail connecting to MinIO."
    echo "  MINIO_ROOT_USER=$MINIO_ROOT_USER vs AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID"
    echo ""
    read -p "Continue anyway? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# ── Create required directories ─────────────────────────────────────────────
echo "[start] Creating required directories..."
mkdir -p ./minio_data
mkdir -p ./trino/catalog

# Ensure Trino data path exists (on host for volume mount)
if [ ! -d "$USER_DATA_PATH" ]; then
    echo "[start] Creating Trino data path: ${USER_DATA_PATH}"
    mkdir -p "$USER_DATA_PATH" 2>/dev/null || \
        echo "[start] WARNING: Cannot create ${USER_DATA_PATH} — ensure it exists"
fi

# Ensure scripts are executable
chmod +x ./scripts/*.sh 2>/dev/null || true

# ── Start stack ─────────────────────────────────────────────────────────────
echo "[start] Starting Iceberg Lakehouse stack..."
echo ""
docker compose up -d --build

echo ""
echo "============================================================"
echo "  Iceberg Lakehouse Stack — Starting"
echo "============================================================"
echo ""
echo "  Services:"
echo "    MinIO Console   : http://localhost:9001"
echo "    Polaris Catalog : http://localhost:8181"
echo "    Trino UI        : http://localhost:8900"
echo "    Lakehouse API   : http://localhost:8100"
echo "    API Docs        : http://localhost:8100/docs"
echo ""

docker compose ps

# ── Optional: Run verification ──────────────────────────────────────────────
if [ "${1:-}" = "--verify" ]; then
    echo ""
    echo "[start] Waiting 30s for services to stabilize..."
    sleep 30
    echo ""
    ./scripts/verify-stack.sh
fi
