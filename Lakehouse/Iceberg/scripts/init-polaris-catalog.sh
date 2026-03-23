#!/bin/bash
# =============================================================================
# Polaris Iceberg Catalog Initialization Script
# =============================================================================
# Bootstraps the Apache Polaris REST catalog with required warehouses,
# namespaces, and principal roles for the Digital Twin Lakehouse.
#
# Designed to run as a one-shot init container after Polaris is healthy.
#
# Required environment variables:
#   POLARIS_URL              — Polaris Management API (default: http://polaris:8181)
#   POLARIS_ROOT_CLIENT_ID   — Bootstrap principal client ID
#   POLARIS_ROOT_CLIENT_SECRET — Bootstrap principal secret
#   ICEBERG_WAREHOUSE        — Warehouse name (default: iceberg2)
#   ICEBERG_NAMESPACE        — Default namespace (default: static_db)
#   S3_BUCKET                — S3 bucket for warehouse data
#   AWS_REGION               — AWS region (default: us-east-1)
# =============================================================================
set -euo pipefail

POLARIS_URL="${POLARIS_URL:-http://polaris:8181}"
POLARIS_ROOT_CLIENT_ID="${POLARIS_ROOT_CLIENT_ID:-root}"
POLARIS_ROOT_CLIENT_SECRET="${POLARIS_ROOT_CLIENT_SECRET:-s3cr3t00}"
ICEBERG_WAREHOUSE="${ICEBERG_WAREHOUSE:-iceberg2}"
ICEBERG_NAMESPACE="${ICEBERG_NAMESPACE:-static_db}"
S3_BUCKET="${S3_BUCKET:-warehouse2}"
AWS_REGION="${AWS_REGION:-us-east-1}"
MAX_RETRIES="${MAX_RETRIES:-30}"
RETRY_INTERVAL="${RETRY_INTERVAL:-3}"

API_BASE="${POLARIS_URL}/api/catalog"
MGMT_BASE="${POLARIS_URL}/api/management/v1"

# ─── Wait for Polaris ────────────────────────────────────────────────────────
echo "[init-polaris] Waiting for Polaris at ${POLARIS_URL}..."
HEALTH_URL="${POLARIS_URL/8181/8182}/q/health"

for i in $(seq 1 "$MAX_RETRIES"); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
        echo "[init-polaris] Polaris is ready (attempt ${i}/${MAX_RETRIES})"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[init-polaris] ERROR: Polaris not available after ${MAX_RETRIES} attempts"
        exit 1
    fi
    echo "[init-polaris] Polaris not ready (${i}/${MAX_RETRIES})..."
    sleep "$RETRY_INTERVAL"
done

# ─── Obtain OAuth2 Token ────────────────────────────────────────────────────
echo "[init-polaris] Obtaining OAuth2 token..."
TOKEN_RESPONSE=$(curl -sf -X POST "${API_BASE}/v1/oauth/tokens" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${POLARIS_ROOT_CLIENT_ID}&client_secret=${POLARIS_ROOT_CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

if [ -z "$ACCESS_TOKEN" ]; then
    echo "[init-polaris] ERROR: Failed to obtain access token"
    echo "[init-polaris] Response: ${TOKEN_RESPONSE}"
    exit 1
fi

echo "[init-polaris] Token obtained successfully"

AUTH_HEADER="Authorization: Bearer ${ACCESS_TOKEN}"

# ─── Helper: Polaris API call ────────────────────────────────────────────────
polaris_api() {
    local method="$1"
    local url="$2"
    local data="${3:-}"

    if [ -n "$data" ]; then
        curl -sf -X "$method" "$url" \
            -H "$AUTH_HEADER" \
            -H "Content-Type: application/json" \
            -d "$data" 2>/dev/null
    else
        curl -sf -X "$method" "$url" \
            -H "$AUTH_HEADER" 2>/dev/null
    fi
}

# ─── Create Warehouse (Catalog) ─────────────────────────────────────────────
echo "[init-polaris] Checking warehouse '${ICEBERG_WAREHOUSE}'..."

EXISTING=$(polaris_api GET "${MGMT_BASE}/catalogs/${ICEBERG_WAREHOUSE}" || echo "")

if echo "$EXISTING" | grep -q '"name"'; then
    echo "[init-polaris] Warehouse '${ICEBERG_WAREHOUSE}' already exists — skipping"
else
    echo "[init-polaris] Creating warehouse '${ICEBERG_WAREHOUSE}'..."
    CREATE_RESULT=$(polaris_api POST "${MGMT_BASE}/catalogs" "{
        \"catalog\": {
            \"name\": \"${ICEBERG_WAREHOUSE}\",
            \"type\": \"INTERNAL\",
            \"properties\": {
                \"default-base-location\": \"s3://${S3_BUCKET}/\"
            },
            \"storageConfigInfo\": {
                \"storageType\": \"S3\",
                \"allowedLocations\": [\"s3://${S3_BUCKET}/\"],
                \"roleArn\": \"arn:aws:iam::000000000000:role/placeholder\"
            }
        }
    }" || echo "FAILED")

    if echo "$CREATE_RESULT" | grep -q "FAILED"; then
        echo "[init-polaris] WARNING: Warehouse creation may have failed (could be pre-existing)"
    else
        echo "[init-polaris] Warehouse '${ICEBERG_WAREHOUSE}' created"
    fi
fi

# ─── Grant catalog access to root principal ──────────────────────────────────
echo "[init-polaris] Granting catalog admin to root principal role..."
polaris_api PUT "${MGMT_BASE}/principal-roles/root/catalog-roles/${ICEBERG_WAREHOUSE}" \
    "{\"catalogRole\": {\"name\": \"catalog_admin\"}}" || true

# ─── Grant CATALOG_MANAGE_CONTENT privilege ──────────────────────────────────
echo "[init-polaris] Granting CATALOG_MANAGE_CONTENT to catalog_admin..."
polaris_api PUT "${MGMT_BASE}/catalogs/${ICEBERG_WAREHOUSE}/catalog-roles/catalog_admin/grants" \
    "{\"grant\":{\"type\":\"catalog\",\"privilege\":\"CATALOG_MANAGE_CONTENT\"}}" || true

# ─── Create Namespace ───────────────────────────────────────────────────────
echo "[init-polaris] Checking namespace '${ICEBERG_NAMESPACE}'..."

NS_EXISTS=$(polaris_api GET "${API_BASE}/v1/${ICEBERG_WAREHOUSE}/namespaces/${ICEBERG_NAMESPACE}" || echo "")

if echo "$NS_EXISTS" | grep -q '"namespace"'; then
    echo "[init-polaris] Namespace '${ICEBERG_NAMESPACE}' already exists — skipping"
else
    echo "[init-polaris] Creating namespace '${ICEBERG_NAMESPACE}'..."
    polaris_api POST "${API_BASE}/v1/${ICEBERG_WAREHOUSE}/namespaces" "{
        \"namespace\": [\"${ICEBERG_NAMESPACE}\"],
        \"properties\": {
            \"location\": \"s3://${S3_BUCKET}/${ICEBERG_NAMESPACE}/\",
            \"description\": \"Static and dynamic object data for Digital Twin\"
        }
    }" || echo "[init-polaris] WARNING: Namespace creation returned non-zero (may already exist)"
fi

# ─── Create Dynamic objects namespace ────────────────────────────────────────
DYNAMIC_NS="dynamic_db"
echo "[init-polaris] Checking namespace '${DYNAMIC_NS}'..."

DNS_EXISTS=$(polaris_api GET "${API_BASE}/v1/${ICEBERG_WAREHOUSE}/namespaces/${DYNAMIC_NS}" || echo "")

if echo "$DNS_EXISTS" | grep -q '"namespace"'; then
    echo "[init-polaris] Namespace '${DYNAMIC_NS}' already exists — skipping"
else
    echo "[init-polaris] Creating namespace '${DYNAMIC_NS}'..."
    polaris_api POST "${API_BASE}/v1/${ICEBERG_WAREHOUSE}/namespaces" "{
        \"namespace\": [\"${DYNAMIC_NS}\"],
        \"properties\": {
            \"location\": \"s3://${S3_BUCKET}/${DYNAMIC_NS}/\",
            \"description\": \"Per-object dynamic sensor data tables\"
        }
    }" || echo "[init-polaris] WARNING: Dynamic namespace creation returned non-zero"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "[init-polaris] ======================================"
echo "[init-polaris]  Catalog initialization complete"
echo "[init-polaris]  Warehouse : ${ICEBERG_WAREHOUSE}"
echo "[init-polaris]  Namespaces: ${ICEBERG_NAMESPACE}, ${DYNAMIC_NS}"
echo "[init-polaris]  S3 Bucket : ${S3_BUCKET}"
echo "[init-polaris] ======================================"
