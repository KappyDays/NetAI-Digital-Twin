#!/bin/bash
# =============================================================================
# Docker Compose Stack Health Verification Script
# =============================================================================
# Validates that all services in the Iceberg Lakehouse stack are healthy
# and properly configured. Run after `docker compose up -d` to verify
# the entire stack is operational.
#
# Exit codes:
#   0 — All checks passed
#   1 — One or more checks failed
#
# Usage:
#   ./scripts/verify-stack.sh
#   ./scripts/verify-stack.sh --verbose
# =============================================================================
set -euo pipefail

VERBOSE="${1:-}"
PASS=0
FAIL=0
WARN=0

# Colors (works on both Windows Terminal and Linux)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

pass() { ((PASS++)); echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { ((FAIL++)); echo -e "${RED}[FAIL]${NC} $1"; }
warn() { ((WARN++)); echo -e "${YELLOW}[WARN]${NC} $1"; }
info() { echo -e "${BLUE}[INFO]${NC} $1"; }

# ─── Load .env for default values ───────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/../.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
    info "Loaded environment from ${ENV_FILE}"
else
    warn ".env file not found at ${ENV_FILE} — using defaults"
fi

MINIO_API="${MINIO_API:-http://localhost:9000}"
MINIO_CONSOLE="${MINIO_CONSOLE:-http://localhost:9001}"
POLARIS_URL="${POLARIS_URL:-http://localhost:8181}"
POLARIS_HEALTH="${POLARIS_HEALTH:-http://localhost:8182/q/health}"
TRINO_URL="${TRINO_URL:-http://localhost:8900}"
API_URL="${API_URL:-http://localhost:8100}"
S3_BUCKET="${S3_BUCKET:-warehouse2}"
ICEBERG_NAMESPACE="${ICEBERG_NAMESPACE:-netai}"

echo ""
echo "============================================================"
echo "  Iceberg Lakehouse Stack — Health Verification"
echo "============================================================"
echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 1. Docker Compose Service Status
# ═════════════════════════════════════════════════════════════════════════════
info "── Docker Compose Services ──"

check_container() {
    local name="$1"
    local status
    status=$(docker inspect --format='{{.State.Health.Status}}' "$name" 2>/dev/null || echo "not_found")

    case "$status" in
        healthy)    pass "Container '${name}' is healthy" ;;
        starting)   warn "Container '${name}' is still starting" ;;
        unhealthy)  fail "Container '${name}' is unhealthy" ;;
        *)
            # Check if container exists but has no healthcheck
            local running
            running=$(docker inspect --format='{{.State.Running}}' "$name" 2>/dev/null || echo "false")
            if [ "$running" = "true" ]; then
                pass "Container '${name}' is running (no healthcheck)"
            else
                fail "Container '${name}' not found or not running"
            fi
            ;;
    esac
}

check_container "minio"
check_container "polaris"
check_container "trino"
check_container "lakehouse-api"

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 2. MinIO Connectivity & Buckets
# ═════════════════════════════════════════════════════════════════════════════
info "── MinIO (S3 Storage) ──"

if curl -sf "${MINIO_API}/minio/health/live" >/dev/null 2>&1; then
    pass "MinIO API is reachable at ${MINIO_API}"
else
    fail "MinIO API not reachable at ${MINIO_API}"
fi

if curl -sf "${MINIO_CONSOLE}" >/dev/null 2>&1; then
    pass "MinIO Console is reachable at ${MINIO_CONSOLE}"
else
    warn "MinIO Console not reachable at ${MINIO_CONSOLE}"
fi

# Check bucket existence via mc (if available) or curl
if command -v mc >/dev/null 2>&1; then
    mc alias set verify_minio "${MINIO_API}" "${AWS_ACCESS_KEY_ID:-admin}" "${AWS_SECRET_ACCESS_KEY:-admin1234}" >/dev/null 2>&1
    if mc ls "verify_minio/${S3_BUCKET}" >/dev/null 2>&1; then
        pass "S3 bucket '${S3_BUCKET}' exists"
    else
        fail "S3 bucket '${S3_BUCKET}' not found"
    fi
else
    info "MinIO client (mc) not available — skipping bucket check"
fi

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 3. Apache Polaris (Iceberg REST Catalog)
# ═════════════════════════════════════════════════════════════════════════════
info "── Apache Polaris (Iceberg Catalog) ──"

if curl -sf "${POLARIS_HEALTH}" >/dev/null 2>&1; then
    pass "Polaris health endpoint is reachable"
else
    fail "Polaris health endpoint not reachable at ${POLARIS_HEALTH}"
fi

# Test OAuth2 token acquisition
TOKEN_RESPONSE=$(curl -sf -X POST "${POLARIS_URL}/api/catalog/v1/oauth/tokens" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${POLARIS_ROOT_CLIENT_ID:-root}&client_secret=${POLARIS_ROOT_CLIENT_SECRET:-s3cr3t00}&scope=PRINCIPAL_ROLE:ALL" 2>/dev/null || echo "FAILED")

if echo "$TOKEN_RESPONSE" | grep -q "access_token"; then
    pass "Polaris OAuth2 token acquisition successful"
else
    fail "Polaris OAuth2 token acquisition failed"
fi

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 4. Trino (SQL Engine)
# ═════════════════════════════════════════════════════════════════════════════
info "── Trino (SQL Query Engine) ──"

TRINO_INFO=$(curl -sf "${TRINO_URL}/v1/info" 2>/dev/null || echo "FAILED")

if echo "$TRINO_INFO" | grep -q '"starting"\|"ACTIVE"'; then
    pass "Trino is reachable and active/starting"

    if [ "$VERBOSE" = "--verbose" ]; then
        info "Trino info: ${TRINO_INFO}"
    fi
else
    fail "Trino not reachable at ${TRINO_URL}"
fi

# Test Trino SQL via REST (simple query)
TRINO_QUERY=$(curl -sf -X POST "${TRINO_URL}/v1/statement" \
    -H "X-Trino-User: verify" \
    -H "X-Trino-Catalog: iceberg" \
    -H "Content-Type: text/plain" \
    -d "SHOW CATALOGS" 2>/dev/null || echo "FAILED")

if echo "$TRINO_QUERY" | grep -q '"id"'; then
    pass "Trino SQL statement submission successful"
else
    fail "Trino SQL statement submission failed"
fi

# Check Iceberg catalog registered
TRINO_CATALOGS=$(curl -sf -X POST "${TRINO_URL}/v1/statement" \
    -H "X-Trino-User: verify" \
    -d "SHOW CATALOGS" 2>/dev/null || echo "FAILED")

if echo "$TRINO_CATALOGS" | grep -q "polaris"; then
    pass "Polaris catalog is registered in Trino"
else
    warn "Could not confirm Polaris catalog (may need async fetch)"
fi

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 5. Lakehouse API Middleware
# ═════════════════════════════════════════════════════════════════════════════
info "── Lakehouse API (FastAPI Middleware) ──"

# Root endpoint
ROOT_RESP=$(curl -sf "${API_URL}/" 2>/dev/null || echo "FAILED")
if echo "$ROOT_RESP" | grep -q "lakehouse-api"; then
    pass "Lakehouse API root endpoint responding"
else
    fail "Lakehouse API root endpoint not responding at ${API_URL}"
fi

# Health endpoint (deep)
HEALTH_RESP=$(curl -sf "${API_URL}/health" 2>/dev/null || echo "FAILED")
if echo "$HEALTH_RESP" | grep -q '"status"'; then
    pass "Lakehouse API /health endpoint responding"

    # Check dependency status
    if echo "$HEALTH_RESP" | grep -q '"healthy"'; then
        pass "Lakehouse API reports healthy dependencies"
    else
        warn "Lakehouse API reports degraded dependencies"
    fi

    if [ "$VERBOSE" = "--verbose" ]; then
        info "Health response: ${HEALTH_RESP}"
    fi
else
    fail "Lakehouse API /health not responding at ${API_URL}/health"
fi

# API v1 health
V1_HEALTH=$(curl -sf "${API_URL}/api/v1/health" 2>/dev/null || echo "FAILED")
if echo "$V1_HEALTH" | grep -q '"status"'; then
    pass "Lakehouse API /api/v1/health endpoint responding"
else
    fail "Lakehouse API /api/v1/health not responding"
fi

# OpenAPI docs
DOCS_RESP=$(curl -sf -o /dev/null -w "%{http_code}" "${API_URL}/docs" 2>/dev/null || echo "000")
if [ "$DOCS_RESP" = "200" ]; then
    pass "Lakehouse API /docs (Swagger UI) accessible"
else
    warn "Lakehouse API /docs returned HTTP ${DOCS_RESP}"
fi

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# 6. End-to-End Connectivity Verification
# ═════════════════════════════════════════════════════════════════════════════
info "── End-to-End Connectivity ──"

# Verify API can reach Trino (via bootstrap status)
if echo "$HEALTH_RESP" | grep -q '"bootstrap"'; then
    BOOTSTRAP_STATUS=$(echo "$HEALTH_RESP" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
    if [ "$BOOTSTRAP_STATUS" = "healthy" ] || [ "$BOOTSTRAP_STATUS" = "ok" ]; then
        pass "API → Trino → Iceberg bootstrap chain verified"
    else
        warn "API bootstrap status: ${BOOTSTRAP_STATUS}"
    fi
fi

# Verify credential consistency
info "Credential consistency check:"
if [ "${MINIO_ROOT_USER:-}" = "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${MINIO_ROOT_USER:-}" ]; then
    pass "MINIO_ROOT_USER matches AWS_ACCESS_KEY_ID"
else
    fail "MINIO_ROOT_USER (${MINIO_ROOT_USER:-unset}) != AWS_ACCESS_KEY_ID (${AWS_ACCESS_KEY_ID:-unset})"
fi

if [ "${MINIO_ROOT_PASSWORD:-}" = "${AWS_SECRET_ACCESS_KEY:-}" ] && [ -n "${MINIO_ROOT_PASSWORD:-}" ]; then
    pass "MINIO_ROOT_PASSWORD matches AWS_SECRET_ACCESS_KEY"
else
    fail "MINIO_ROOT_PASSWORD != AWS_SECRET_ACCESS_KEY (credential mismatch!)"
fi

echo ""

# ═════════════════════════════════════════════════════════════════════════════
# Summary
# ═════════════════════════════════════════════════════════════════════════════
TOTAL=$((PASS + FAIL + WARN))
echo "============================================================"
echo "  Verification Summary"
echo "============================================================"
echo -e "  ${GREEN}PASS${NC}: ${PASS}  |  ${RED}FAIL${NC}: ${FAIL}  |  ${YELLOW}WARN${NC}: ${WARN}  |  Total: ${TOTAL}"
echo "============================================================"

if [ "$FAIL" -gt 0 ]; then
    echo -e "  ${RED}Stack verification FAILED — ${FAIL} check(s) did not pass${NC}"
    echo ""
    echo "  Troubleshooting:"
    echo "    1. Ensure all containers are running: docker compose ps"
    echo "    2. Check logs: docker compose logs <service>"
    echo "    3. Verify .env credentials are consistent"
    echo "    4. Wait for services to fully start (Polaris/Trino can take 30-60s)"
    exit 1
else
    echo -e "  ${GREEN}All critical checks passed!${NC}"
    echo ""
    echo "  Service URLs:"
    echo "    MinIO Console   : ${MINIO_CONSOLE}"
    echo "    Polaris Catalog : ${POLARIS_URL}"
    echo "    Trino UI        : ${TRINO_URL}"
    echo "    Lakehouse API   : ${API_URL}"
    echo "    API Docs        : ${API_URL}/docs"
    exit 0
fi
