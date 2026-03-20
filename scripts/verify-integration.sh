#!/bin/bash
# =============================================================================
# NetAI-Digital-Twin — Integration Verification Script
# =============================================================================
# Automates the full-stack startup and verification:
#   1. Builds & starts all containers via docker compose
#   2. Waits until every container reaches "healthy" status
#   3. Scans container logs for errors
#   4. Runs connectivity tests (MinIO, Polaris, Trino, API, Dashboard)
#
# Exit codes:
#   0 — All checks passed
#   1 — One or more checks failed
#
# Usage:
#   ./scripts/verify-integration.sh                 # Build + verify
#   ./scripts/verify-integration.sh --skip-build    # Verify only (stack already running)
#   ./scripts/verify-integration.sh --verbose        # Extra detail
#   ./scripts/verify-integration.sh --timeout 300    # Custom healthy-wait timeout (sec)
#
# Compatibility:
#   - Windows 11 Docker Desktop (Git Bash / WSL2)
#   - Ubuntu 24.04 headless (docker compose v2)
# =============================================================================
set -euo pipefail

# ─── Parse arguments ─────────────────────────────────────────────────────────
SKIP_BUILD=false
VERBOSE=false
HEALTHY_TIMEOUT=360   # seconds to wait for all containers to be healthy
COMPOSE_FILE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build)   SKIP_BUILD=true; shift ;;
        --verbose)      VERBOSE=true; shift ;;
        --timeout)      HEALTHY_TIMEOUT="$2"; shift 2 ;;
        -f|--file)      COMPOSE_FILE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--skip-build] [--verbose] [--timeout SEC] [-f COMPOSE_FILE]"
            exit 0 ;;
        *)              echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ─── Resolve project root ────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ─── Load .env if available ──────────────────────────────────────────────────
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
elif [ -f "$PROJECT_ROOT/example.env" ]; then
    set -a; source "$PROJECT_ROOT/example.env"; set +a
fi

# ─── Compose command ─────────────────────────────────────────────────────────
COMPOSE_CMD="docker compose"
if [ -n "$COMPOSE_FILE" ]; then
    COMPOSE_CMD="$COMPOSE_CMD -f $COMPOSE_FILE"
fi

# ─── Port & URL defaults (from env or docker-compose.yml defaults) ────────────
MINIO_API_PORT="${MINIO_API_PORT:-9000}"
MINIO_CONSOLE_PORT="${MINIO_CONSOLE_PORT:-9001}"
POLARIS_API_PORT="${POLARIS_API_PORT:-8181}"
POLARIS_MGMT_PORT="${POLARIS_MGMT_PORT:-8182}"
TRINO_PORT="${TRINO_PORT:-8900}"
API_PORT="${API_PORT:-8100}"
DASHBOARD_PORT="${DASHBOARD_PORT:-3000}"

MINIO_URL="http://localhost:${MINIO_API_PORT}"
MINIO_CONSOLE_URL="http://localhost:${MINIO_CONSOLE_PORT}"
POLARIS_URL="http://localhost:${POLARIS_API_PORT}"
POLARIS_HEALTH_URL="http://localhost:${POLARIS_MGMT_PORT}/q/health"
TRINO_URL="http://localhost:${TRINO_PORT}"
API_URL="http://localhost:${API_PORT}"
DASHBOARD_URL="http://localhost:${DASHBOARD_PORT}"

# ─── Counters ─────────────────────────────────────────────────────────────────
PASS=0; FAIL=0; WARN=0; SKIP=0
ERRORS=()

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

pass()  { ((PASS++));  echo -e "  ${GREEN}✓ PASS${NC}  $1"; }
fail()  { ((FAIL++));  echo -e "  ${RED}✗ FAIL${NC}  $1"; ERRORS+=("$1"); }
warn()  { ((WARN++));  echo -e "  ${YELLOW}⚠ WARN${NC}  $1"; }
skip()  { ((SKIP++));  echo -e "  ${CYAN}○ SKIP${NC}  $1"; }
info()  { echo -e "  ${BLUE}ℹ INFO${NC}  $1"; }
header(){ echo -e "\n${BOLD}━━━ $1 ━━━${NC}"; }
ts()    { date '+%H:%M:%S'; }

# ─── Utility: HTTP status check ──────────────────────────────────────────────
http_ok() {
    local url="$1"
    local code
    code=$(curl -sf -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$url" 2>/dev/null || echo "000")
    [ "$code" -ge 200 ] && [ "$code" -lt 400 ]
}

http_get() {
    curl -sf --connect-timeout 5 --max-time 10 "$@" 2>/dev/null || echo ""
}

# =============================================================================
echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   NetAI-Digital-Twin — Integration Verification        ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo -e "  Started at $(ts)  |  Project: ${PROJECT_ROOT}"
echo ""

# =============================================================================
# PHASE 1: Build & Start
# =============================================================================
header "PHASE 1: Docker Compose Build & Start"

if [ "$SKIP_BUILD" = true ]; then
    info "Skipping build (--skip-build flag set)"
else
    info "Running: docker compose up -d --build"
    echo ""

    if $COMPOSE_CMD up -d --build 2>&1; then
        pass "docker compose up -d --build succeeded"
    else
        fail "docker compose up -d --build failed"
        echo -e "\n${RED}Build failed. Check Dockerfiles and docker-compose.yml${NC}"
        exit 1
    fi
    echo ""
fi

# =============================================================================
# PHASE 2: Wait for All Containers to Become Healthy
# =============================================================================
header "PHASE 2: Container Health Status"

# Expected containers from root docker-compose.yml
EXPECTED_CONTAINERS=(
    "dt-minio"
    "dt-polaris"
    "dt-trino"
    "dt-lakehouse-api"
    "dt-spark"
    "dt-dashboard"
)

# Also check if spark-worker is running (no healthcheck defined)
NOHEALTH_CONTAINERS=(
    "dt-spark-worker"
)

info "Waiting up to ${HEALTHY_TIMEOUT}s for containers to become healthy..."
echo ""

wait_healthy() {
    local container="$1"
    local timeout="$2"
    local elapsed=0
    local interval=5

    while [ "$elapsed" -lt "$timeout" ]; do
        local status
        status=$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo "not_found")

        case "$status" in
            healthy)    return 0 ;;
            unhealthy)  return 1 ;;
            not_found)  return 2 ;;
        esac

        sleep "$interval"
        elapsed=$((elapsed + interval))
    done
    return 3  # timeout
}

# Track overall healthy wait
ALL_HEALTHY=true
TOTAL_START=$SECONDS

for cname in "${EXPECTED_CONTAINERS[@]}"; do
    # Check container exists first
    if ! docker inspect "$cname" >/dev/null 2>&1; then
        fail "Container '${cname}' does not exist"
        ALL_HEALTHY=false
        continue
    fi

    # Wait for healthy
    wait_healthy "$cname" "$HEALTHY_TIMEOUT"
    rc=$?

    case $rc in
        0) pass "Container '${cname}' is healthy" ;;
        1) fail "Container '${cname}' is unhealthy"; ALL_HEALTHY=false ;;
        2) fail "Container '${cname}' not found"; ALL_HEALTHY=false ;;
        3) fail "Container '${cname}' timed out (not healthy within ${HEALTHY_TIMEOUT}s)"; ALL_HEALTHY=false ;;
    esac
done

# Check containers without healthcheck
for cname in "${NOHEALTH_CONTAINERS[@]}"; do
    if docker inspect --format='{{.State.Running}}' "$cname" 2>/dev/null | grep -q "true"; then
        pass "Container '${cname}' is running (no healthcheck)"
    else
        warn "Container '${cname}' not running (optional service)"
    fi
done

HEALTHY_ELAPSED=$((SECONDS - TOTAL_START))
info "Health check phase completed in ${HEALTHY_ELAPSED}s"

# =============================================================================
# PHASE 3: Error Log Detection
# =============================================================================
header "PHASE 3: Container Log Analysis"

ALL_CONTAINERS=("${EXPECTED_CONTAINERS[@]}" "${NOHEALTH_CONTAINERS[@]}")

# Error patterns to detect (case-insensitive grep)
# Exclude common false positives
ERROR_PATTERNS='(ERROR|FATAL|CRITICAL|panic|Traceback|Exception.*Error|failed to start)'
EXCLUDE_PATTERNS='(HealthCheck|metrics|DEBUG|\.error_count|error_page|error_log|ErrorCode|errorMessage.*null|NoSuchKey)'

CONTAINERS_WITH_ERRORS=0

for cname in "${ALL_CONTAINERS[@]}"; do
    if ! docker inspect "$cname" >/dev/null 2>&1; then
        continue
    fi

    # Get last 200 lines of logs
    LOGS=$(docker logs --tail 200 "$cname" 2>&1 || echo "")

    # Count error lines (excluding false positives)
    ERROR_COUNT=$(echo "$LOGS" | grep -iE "$ERROR_PATTERNS" | grep -ivE "$EXCLUDE_PATTERNS" | wc -l || echo "0")
    ERROR_COUNT=$(echo "$ERROR_COUNT" | tr -d '[:space:]')

    if [ "$ERROR_COUNT" -gt 0 ]; then
        warn "Container '${cname}': ${ERROR_COUNT} potential error line(s) in recent logs"
        ((CONTAINERS_WITH_ERRORS++)) || true

        if [ "$VERBOSE" = true ]; then
            echo -e "    ${YELLOW}--- Error excerpts (last 5) ---${NC}"
            echo "$LOGS" | grep -iE "$ERROR_PATTERNS" | grep -ivE "$EXCLUDE_PATTERNS" | tail -5 | while IFS= read -r line; do
                echo -e "    ${YELLOW}│${NC} $(echo "$line" | head -c 120)"
            done
            echo -e "    ${YELLOW}-------------------------------${NC}"
        fi
    else
        pass "Container '${cname}': no errors in recent logs"
    fi
done

if [ "$CONTAINERS_WITH_ERRORS" -eq 0 ]; then
    info "No error logs detected across all containers"
else
    info "${CONTAINERS_WITH_ERRORS} container(s) have potential errors (use --verbose for details)"
fi

# =============================================================================
# PHASE 4: Connectivity & Functional Tests
# =============================================================================
header "PHASE 4: Service Connectivity Tests"

# ── 4.1 MinIO ────────────────────────────────────────────────────────────────
echo -e "\n  ${BOLD}[MinIO — S3 Object Storage]${NC}"

if http_ok "${MINIO_URL}/minio/health/live"; then
    pass "MinIO S3 API live at ${MINIO_URL}"
else
    fail "MinIO S3 API not reachable at ${MINIO_URL}"
fi

if http_ok "${MINIO_URL}/minio/health/ready"; then
    pass "MinIO readiness check passed"
else
    warn "MinIO readiness check failed (may still be initializing)"
fi

if http_ok "${MINIO_CONSOLE_URL}"; then
    pass "MinIO Console accessible at ${MINIO_CONSOLE_URL}"
else
    warn "MinIO Console not reachable at ${MINIO_CONSOLE_URL}"
fi

# ── 4.2 Polaris ──────────────────────────────────────────────────────────────
echo -e "\n  ${BOLD}[Apache Polaris — Iceberg REST Catalog]${NC}"

if http_ok "$POLARIS_HEALTH_URL"; then
    pass "Polaris health endpoint OK"
else
    fail "Polaris health endpoint not reachable at ${POLARIS_HEALTH_URL}"
fi

# OAuth2 token test
POLARIS_CLIENT_ID="${POLARIS_ROOT_CLIENT_ID:-root}"
POLARIS_CLIENT_SECRET="${POLARIS_ROOT_CLIENT_SECRET:-s3cr3t00}"

TOKEN_RESP=$(http_get -X POST "${POLARIS_URL}/api/catalog/v1/oauth/tokens" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials&client_id=${POLARIS_CLIENT_ID}&client_secret=${POLARIS_CLIENT_SECRET}&scope=PRINCIPAL_ROLE:ALL")

if echo "$TOKEN_RESP" | grep -q "access_token"; then
    pass "Polaris OAuth2 token acquisition succeeded"
    ACCESS_TOKEN=$(echo "$TOKEN_RESP" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)

    # Check warehouse exists
    WH_RESP=$(http_get -H "Authorization: Bearer ${ACCESS_TOKEN}" \
        "${POLARIS_URL}/api/management/v1/catalogs/${ICEBERG_WAREHOUSE:-iceberg2}")
    if echo "$WH_RESP" | grep -q '"name"'; then
        pass "Polaris warehouse '${ICEBERG_WAREHOUSE:-iceberg2}' exists"
    else
        warn "Polaris warehouse '${ICEBERG_WAREHOUSE:-iceberg2}' not found (run init-polaris-catalog.sh)"
    fi

    # Check namespaces
    for ns in "${ICEBERG_NAMESPACE:-static_db}" "dynamic_db"; do
        NS_RESP=$(http_get -H "Authorization: Bearer ${ACCESS_TOKEN}" \
            "${POLARIS_URL}/api/catalog/v1/${ICEBERG_WAREHOUSE:-iceberg2}/namespaces/${ns}")
        if echo "$NS_RESP" | grep -q '"namespace"'; then
            pass "Polaris namespace '${ns}' exists"
        else
            warn "Polaris namespace '${ns}' not found"
        fi
    done
else
    fail "Polaris OAuth2 token acquisition failed"
fi

# ── 4.3 Trino ────────────────────────────────────────────────────────────────
echo -e "\n  ${BOLD}[Trino — SQL Query Engine]${NC}"

TRINO_INFO=$(http_get "${TRINO_URL}/v1/info")

if echo "$TRINO_INFO" | grep -qE '"starting"|"ACTIVE"'; then
    pass "Trino is active at ${TRINO_URL}"

    if [ "$VERBOSE" = true ]; then
        info "Trino info: ${TRINO_INFO}"
    fi
else
    fail "Trino not reachable or not active at ${TRINO_URL}"
fi

# Trino SQL test
TRINO_STMT=$(http_get -X POST "${TRINO_URL}/v1/statement" \
    -H "X-Trino-User: verify" \
    -H "X-Trino-Catalog: iceberg" \
    -H "Content-Type: text/plain" \
    -d "SHOW CATALOGS")

if echo "$TRINO_STMT" | grep -q '"id"'; then
    pass "Trino SQL statement submission works"
else
    fail "Trino SQL statement submission failed"
fi

# ── 4.4 Lakehouse API (FastAPI) ──────────────────────────────────────────────
echo -e "\n  ${BOLD}[Lakehouse API — FastAPI Middleware]${NC}"

# Root
ROOT_RESP=$(http_get "${API_URL}/")
if echo "$ROOT_RESP" | grep -qi "lakehouse"; then
    pass "API root endpoint responds"
else
    fail "API root endpoint not responding at ${API_URL}/"
fi

# Health
HEALTH_RESP=$(http_get "${API_URL}/health")
if echo "$HEALTH_RESP" | grep -q '"status"'; then
    pass "API /health endpoint responds"

    if echo "$HEALTH_RESP" | grep -q '"healthy"'; then
        pass "API reports all dependencies healthy"
    else
        warn "API reports degraded dependencies"
        if [ "$VERBOSE" = true ]; then
            info "Health response: ${HEALTH_RESP}"
        fi
    fi
else
    fail "API /health endpoint not responding"
fi

# API v1 health
V1_HEALTH=$(http_get "${API_URL}/api/v1/health")
if echo "$V1_HEALTH" | grep -q '"status"'; then
    pass "API /api/v1/health endpoint responds"
else
    fail "API /api/v1/health not responding"
fi

# Swagger docs
if http_ok "${API_URL}/docs"; then
    pass "API /docs (Swagger UI) accessible"
else
    warn "API /docs not accessible"
fi

# OpenAPI schema
if http_ok "${API_URL}/openapi.json"; then
    pass "API /openapi.json schema accessible"
else
    warn "API /openapi.json not accessible"
fi

# ── 4.5 Dashboard ────────────────────────────────────────────────────────────
echo -e "\n  ${BOLD}[Web Dashboard — React SPA]${NC}"

if http_ok "${DASHBOARD_URL}"; then
    pass "Dashboard accessible at ${DASHBOARD_URL}"
else
    warn "Dashboard not accessible at ${DASHBOARD_URL} (may still be building)"
fi

# =============================================================================
# PHASE 5: Cross-Service Integration Checks
# =============================================================================
header "PHASE 5: Cross-Service Integration"

# API → Trino connectivity (via health response)
if echo "$HEALTH_RESP" | grep -q '"trino"'; then
    TRINO_DEP=$(echo "$HEALTH_RESP" | grep -o '"trino"[^}]*}' | head -1)
    if echo "$TRINO_DEP" | grep -qi '"healthy"\|"ok"\|true'; then
        pass "API → Trino connectivity verified (via /health)"
    else
        warn "API → Trino dependency status unclear"
    fi
else
    info "API /health does not expose Trino dependency detail — skipping"
fi

# API → MinIO connectivity (via health response)
if echo "$HEALTH_RESP" | grep -q '"minio"\|"s3"'; then
    S3_DEP=$(echo "$HEALTH_RESP" | grep -o '"minio"[^}]*}\|"s3"[^}]*}' | head -1)
    if echo "$S3_DEP" | grep -qi '"healthy"\|"ok"\|true'; then
        pass "API → MinIO/S3 connectivity verified (via /health)"
    else
        warn "API → MinIO/S3 dependency status unclear"
    fi
else
    info "API /health does not expose S3 dependency detail — skipping"
fi

# Credential consistency
echo ""
info "Credential consistency:"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-admin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-admin1234}"
AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-admin}"
AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-admin1234}"

if [ "$MINIO_ROOT_USER" = "$AWS_ACCESS_KEY_ID" ]; then
    pass "MINIO_ROOT_USER matches AWS_ACCESS_KEY_ID"
else
    fail "MINIO_ROOT_USER (${MINIO_ROOT_USER}) ≠ AWS_ACCESS_KEY_ID (${AWS_ACCESS_KEY_ID})"
fi

if [ "$MINIO_ROOT_PASSWORD" = "$AWS_SECRET_ACCESS_KEY" ]; then
    pass "MINIO_ROOT_PASSWORD matches AWS_SECRET_ACCESS_KEY"
else
    fail "MINIO_ROOT_PASSWORD ≠ AWS_SECRET_ACCESS_KEY (credential mismatch!)"
fi

# =============================================================================
# Summary
# =============================================================================
TOTAL=$((PASS + FAIL + WARN + SKIP))
ELAPSED=$((SECONDS))

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║   Verification Summary                                 ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}  ${GREEN}PASS${NC}: ${PASS}  │  ${RED}FAIL${NC}: ${FAIL}  │  ${YELLOW}WARN${NC}: ${WARN}  │  ${CYAN}SKIP${NC}: ${SKIP}  │  Total: ${TOTAL}  ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  Elapsed: ${ELAPSED}s                                         ${BOLD}║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo -e "  ${RED}${BOLD}RESULT: FAILED${NC} — ${FAIL} check(s) did not pass"
    echo ""
    echo -e "  ${RED}Failed checks:${NC}"
    for err in "${ERRORS[@]}"; do
        echo -e "    ${RED}•${NC} ${err}"
    done
    echo ""
    echo "  Troubleshooting:"
    echo "    1. Check container status:   docker compose ps"
    echo "    2. View container logs:      docker compose logs <service>"
    echo "    3. Verify .env credentials:  cat .env"
    echo "    4. Restart specific service: docker compose restart <service>"
    echo "    5. Full rebuild:             docker compose up -d --build --force-recreate"
    echo ""

    # Dump unhealthy container logs if verbose
    if [ "$VERBOSE" = true ]; then
        echo -e "  ${YELLOW}--- Unhealthy Container Logs ---${NC}"
        for cname in "${ALL_CONTAINERS[@]}"; do
            local_status=$(docker inspect --format='{{.State.Health.Status}}' "$cname" 2>/dev/null || echo "unknown")
            if [ "$local_status" = "unhealthy" ]; then
                echo -e "\n  ${RED}=== ${cname} (unhealthy) ===${NC}"
                docker logs --tail 30 "$cname" 2>&1 | sed 's/^/    /'
            fi
        done
    fi

    exit 1
else
    echo ""
    echo -e "  ${GREEN}${BOLD}RESULT: ALL CHECKS PASSED${NC}"
    echo ""
    echo "  Service URLs:"
    echo "    MinIO Console   : ${MINIO_CONSOLE_URL}"
    echo "    Polaris Catalog : ${POLARIS_URL}"
    echo "    Trino UI        : ${TRINO_URL}"
    echo "    Lakehouse API   : ${API_URL}"
    echo "    API Docs        : ${API_URL}/docs"
    echo "    Dashboard       : ${DASHBOARD_URL}"
    echo ""
    exit 0
fi
