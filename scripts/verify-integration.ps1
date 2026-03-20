# =============================================================================
# NetAI-Digital-Twin — Integration Verification Script (PowerShell)
# =============================================================================
# Windows-native verification script for Docker Desktop environments.
# Equivalent to verify-integration.sh for Bash.
#
# Usage:
#   .\scripts\verify-integration.ps1                    # Build + verify
#   .\scripts\verify-integration.ps1 -SkipBuild         # Verify only
#   .\scripts\verify-integration.ps1 -Verbose           # Extra detail
#   .\scripts\verify-integration.ps1 -Timeout 300       # Custom timeout (sec)
# =============================================================================
[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [int]$Timeout = 360,
    [string]$ComposeFile = ""
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $ProjectRoot

# ─── Load .env ────────────────────────────────────────────────────────────────
$envFile = if (Test-Path ".env") { ".env" } elseif (Test-Path "example.env") { "example.env" } else { $null }
$envVars = @{}
if ($envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $envVars[$Matches[1].Trim()] = $Matches[2].Trim()
        }
    }
}

function Get-EnvOrDefault($key, $default) {
    if ($envVars.ContainsKey($key)) { return $envVars[$key] }
    return $default
}

# ─── Ports & URLs ─────────────────────────────────────────────────────────────
$MinioPort      = Get-EnvOrDefault "MINIO_API_PORT" "9000"
$MinioConsole   = Get-EnvOrDefault "MINIO_CONSOLE_PORT" "9001"
$PolarisPort    = Get-EnvOrDefault "POLARIS_API_PORT" "8181"
$PolarisMgmt    = Get-EnvOrDefault "POLARIS_MGMT_PORT" "8182"
$TrinoPort      = Get-EnvOrDefault "TRINO_PORT" "8900"
$ApiPort        = Get-EnvOrDefault "API_PORT" "8100"
$DashboardPort  = Get-EnvOrDefault "DASHBOARD_PORT" "3000"

$Urls = @{
    MinioApi      = "http://localhost:$MinioPort"
    MinioConsole  = "http://localhost:$MinioConsole"
    PolarisHealth = "http://localhost:${PolarisMgmt}/q/health"
    Polaris       = "http://localhost:$PolarisPort"
    Trino         = "http://localhost:$TrinoPort"
    Api           = "http://localhost:$ApiPort"
    Dashboard     = "http://localhost:$DashboardPort"
}

# ─── Counters ─────────────────────────────────────────────────────────────────
$script:Pass = 0; $script:Fail = 0; $script:Warn = 0
$script:Errors = @()

function Write-Pass($msg)  { $script:Pass++; Write-Host "  + PASS  $msg" -ForegroundColor Green }
function Write-Fail($msg)  { $script:Fail++; $script:Errors += $msg; Write-Host "  x FAIL  $msg" -ForegroundColor Red }
function Write-Warn($msg)  { $script:Warn++; Write-Host "  ! WARN  $msg" -ForegroundColor Yellow }
function Write-Info($msg)  { Write-Host "  i INFO  $msg" -ForegroundColor Cyan }
function Write-Header($msg){ Write-Host "`n=== $msg ===" -ForegroundColor White }

function Test-Url($url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
    } catch { return $false }
}

function Get-Url($url) {
    try {
        return (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop).Content
    } catch { return "" }
}

# =============================================================================
Write-Host ""
Write-Host "================================================================" -ForegroundColor White
Write-Host "  NetAI-Digital-Twin — Integration Verification (PowerShell)" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor White
Write-Host "  Started: $(Get-Date -Format 'HH:mm:ss')  |  Project: $ProjectRoot"
Write-Host ""

$ComposeCmd = "docker compose"
if ($ComposeFile) { $ComposeCmd += " -f $ComposeFile" }

# ─── Phase 1: Build ──────────────────────────────────────────────────────────
Write-Header "PHASE 1: Docker Compose Build & Start"

if (-not $SkipBuild) {
    Write-Info "Running: docker compose up -d --build"
    $buildResult = & docker compose up -d --build 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Pass "docker compose up -d --build succeeded"
    } else {
        Write-Fail "docker compose up -d --build failed"
        $buildResult | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        exit 1
    }
} else {
    Write-Info "Skipping build (-SkipBuild flag set)"
}

# ─── Phase 2: Container Health ────────────────────────────────────────────────
Write-Header "PHASE 2: Container Health Status"

$ExpectedContainers = @("dt-minio","dt-polaris","dt-trino","dt-lakehouse-api","dt-spark","dt-dashboard")
$NoHealthContainers = @("dt-spark-worker")

Write-Info "Waiting up to ${Timeout}s for containers to become healthy..."

foreach ($cname in $ExpectedContainers) {
    $elapsed = 0
    $healthy = $false
    $status = "unknown"

    while ($elapsed -lt $Timeout) {
        try {
            $status = (docker inspect --format '{{.State.Health.Status}}' $cname 2>$null).Trim()
        } catch { $status = "not_found" }

        if ($status -eq "healthy") { $healthy = $true; break }
        if ($status -eq "unhealthy") { break }
        if ($status -eq "not_found" -or $status -eq "") { break }

        Start-Sleep -Seconds 5
        $elapsed += 5
    }

    if ($healthy) { Write-Pass "Container '$cname' is healthy" }
    elseif ($status -eq "unhealthy") { Write-Fail "Container '$cname' is unhealthy" }
    elseif ($status -eq "not_found" -or $status -eq "") { Write-Fail "Container '$cname' not found" }
    else { Write-Fail "Container '$cname' timed out ($status)" }
}

foreach ($cname in $NoHealthContainers) {
    try {
        $running = (docker inspect --format '{{.State.Running}}' $cname 2>$null).Trim()
        if ($running -eq "true") { Write-Pass "Container '$cname' is running (no healthcheck)" }
        else { Write-Warn "Container '$cname' not running" }
    } catch { Write-Warn "Container '$cname' not found" }
}

# ─── Phase 3: Error Log Detection ────────────────────────────────────────────
Write-Header "PHASE 3: Container Log Analysis"

$allContainers = $ExpectedContainers + $NoHealthContainers
foreach ($cname in $allContainers) {
    try {
        $logs = docker logs --tail 200 $cname 2>&1 | Out-String
        $errorLines = $logs -split "`n" | Where-Object {
            $_ -match '(ERROR|FATAL|CRITICAL|panic|Traceback)' -and
            $_ -notmatch '(HealthCheck|metrics|DEBUG|error_count|error_page|error_log)'
        }
        if ($errorLines.Count -gt 0) {
            Write-Warn "Container '$cname': $($errorLines.Count) potential error line(s)"
        } else {
            Write-Pass "Container '$cname': no errors in recent logs"
        }
    } catch {
        Write-Warn "Could not read logs for '$cname'"
    }
}

# ─── Phase 4: Connectivity Tests ─────────────────────────────────────────────
Write-Header "PHASE 4: Service Connectivity Tests"

# MinIO
Write-Host "`n  [MinIO]" -ForegroundColor White
if (Test-Url "$($Urls.MinioApi)/minio/health/live") { Write-Pass "MinIO S3 API live" } else { Write-Fail "MinIO S3 API not reachable" }
if (Test-Url $Urls.MinioConsole) { Write-Pass "MinIO Console accessible" } else { Write-Warn "MinIO Console not reachable" }

# Polaris
Write-Host "`n  [Polaris]" -ForegroundColor White
if (Test-Url $Urls.PolarisHealth) { Write-Pass "Polaris health OK" } else { Write-Fail "Polaris health not reachable" }

# Trino
Write-Host "`n  [Trino]" -ForegroundColor White
$trinoInfo = Get-Url "$($Urls.Trino)/v1/info"
if ($trinoInfo -match '"starting"|"ACTIVE"') { Write-Pass "Trino active at $($Urls.Trino)" } else { Write-Fail "Trino not active" }

# API
Write-Host "`n  [Lakehouse API]" -ForegroundColor White
$apiRoot = Get-Url "$($Urls.Api)/"
if ($apiRoot -match 'lakehouse') { Write-Pass "API root responds" } else { Write-Fail "API root not responding" }

$apiHealth = Get-Url "$($Urls.Api)/health"
if ($apiHealth -match '"status"') { Write-Pass "API /health responds" } else { Write-Fail "API /health not responding" }

if (Test-Url "$($Urls.Api)/docs") { Write-Pass "API /docs accessible" } else { Write-Warn "API /docs not accessible" }

# Dashboard
Write-Host "`n  [Dashboard]" -ForegroundColor White
if (Test-Url $Urls.Dashboard) { Write-Pass "Dashboard accessible" } else { Write-Warn "Dashboard not accessible" }

# ─── Summary ──────────────────────────────────────────────────────────────────
$Total = $script:Pass + $script:Fail + $script:Warn
Write-Host ""
Write-Host "================================================================" -ForegroundColor White
Write-Host "  Verification Summary" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor White
Write-Host "  PASS: $($script:Pass)  |  FAIL: $($script:Fail)  |  WARN: $($script:Warn)  |  Total: $Total"
Write-Host "================================================================" -ForegroundColor White

if ($script:Fail -gt 0) {
    Write-Host "`n  RESULT: FAILED - $($script:Fail) check(s) did not pass" -ForegroundColor Red
    Write-Host "`n  Failed checks:" -ForegroundColor Red
    $script:Errors | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  Troubleshooting:"
    Write-Host "    1. docker compose ps"
    Write-Host "    2. docker compose logs <service>"
    Write-Host "    3. Verify .env credentials"
    exit 1
} else {
    Write-Host "`n  RESULT: ALL CHECKS PASSED" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Service URLs:"
    Write-Host "    MinIO Console   : $($Urls.MinioConsole)"
    Write-Host "    Polaris Catalog : $($Urls.Polaris)"
    Write-Host "    Trino UI        : $($Urls.Trino)"
    Write-Host "    Lakehouse API   : $($Urls.Api)"
    Write-Host "    API Docs        : $($Urls.Api)/docs"
    Write-Host "    Dashboard       : $($Urls.Dashboard)"
    exit 0
}
