#!/bin/bash
# =============================================================================
# MinIO Bucket Initialization Script
# =============================================================================
# Creates required S3 buckets for the Iceberg Lakehouse stack.
# Designed to run as a one-shot init container in docker-compose.
#
# Required environment variables:
#   MINIO_ENDPOINT    — MinIO API URL (default: http://minio:9000)
#   AWS_ACCESS_KEY_ID — MinIO root user
#   AWS_SECRET_ACCESS_KEY — MinIO root password
#   S3_BUCKET         — Primary warehouse bucket (default: warehouse2)
# =============================================================================
set -euo pipefail

MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
S3_BUCKET="${S3_BUCKET:-warehouse2}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-2}"

echo "[init-minio] Waiting for MinIO at ${MINIO_ENDPOINT}..."

# Wait for MinIO to be ready
for i in $(seq 1 "$MAX_RETRIES"); do
    if mc alias set myminio "$MINIO_ENDPOINT" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" >/dev/null 2>&1; then
        echo "[init-minio] MinIO is ready (attempt ${i}/${MAX_RETRIES})"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[init-minio] ERROR: MinIO not available after ${MAX_RETRIES} attempts"
        exit 1
    fi
    echo "[init-minio] MinIO not ready, retrying in ${RETRY_INTERVAL}s (${i}/${MAX_RETRIES})..."
    sleep "$RETRY_INTERVAL"
done

# Create buckets (idempotent — skips if already exists)
create_bucket() {
    local bucket="$1"
    if mc ls "myminio/${bucket}" >/dev/null 2>&1; then
        echo "[init-minio] Bucket '${bucket}' already exists — skipping"
    else
        mc mb "myminio/${bucket}"
        echo "[init-minio] Created bucket '${bucket}'"
    fi
}

echo "[init-minio] Ensuring required buckets exist..."

# Primary warehouse bucket (Iceberg table data)
create_bucket "$S3_BUCKET"

# USD assets bucket (scene files uploaded via API)
create_bucket "usd-assets"

# List all buckets for verification
echo "[init-minio] Current buckets:"
mc ls myminio/

echo "[init-minio] Bucket initialization complete."
