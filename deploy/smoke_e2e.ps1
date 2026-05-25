<#
.SYNOPSIS
    AI Assurance E2E smoke wrapper — Session 44 V2-PORTAL-SPLIT split.

.DESCRIPTION
    Thin orchestrator. The actual probes live in three focused scripts:
      * deploy/smoke_api.ps1     — engine API surfaces + A6/A7 login redirect (7 probes)
      * deploy/smoke_portal.ps1  — Team Workspace SPA load (3 probes)
      * deploy/smoke_gov.ps1     — CISO Console SPA load (3 probes)

    This wrapper runs all three in sequence, threads through their environment
    variables, and aggregates exit codes. Retained for backward compatibility
    with existing CI hooks and operator muscle memory. Delete after V2 cutover
    once CI references all three scripts directly.

    Each child script is INVOKED in its own pwsh process so a hard failure in
    one (e.g. exit 99 host-allowlist abort in smoke_api) does not abort the
    siblings. Exit code = sum of child exit codes; non-zero = something failed.

    Environment variables read (passed through to children):
      SMOKE_TARGET_URL  → smoke_api    (engine base URL)
      SMOKE_USER        → smoke_api    (operator login username)
      SMOKE_PASSWORD    → smoke_api    (operator login password)
      SMOKE_ENGINEER_PW → smoke_api    (demo-engineer password — for A6 probe)
      SMOKE_CISO_PW     → smoke_api    (demo-ciso password — for A7 probe)
      PORTAL_URL        → smoke_api    (expected engineer-redirect target)
      GOV_URL           → smoke_api    (expected ciso-redirect target)
      SMOKE_PORTAL_URL  → smoke_portal (Team Workspace SPA base URL)
      SMOKE_GOV_URL     → smoke_gov    (CISO Console SPA base URL)
      SMOKE_ALLOW_PROD  → smoke_api    (override host allowlist)

.EXAMPLE
    # Dev — engine only (SPA probes will SKIP if SWA hostnames unreachable):
    $env:SMOKE_TARGET_URL = "http://localhost:8000"
    pwsh deploy/smoke_e2e.ps1

    # Full staging sweep:
    $env:SMOKE_TARGET_URL = "https://api.aigovern.sandboxhub.co"
    $env:SMOKE_USER       = "demo-aigov"
    $env:SMOKE_PASSWORD   = "<password>"
    pwsh deploy/smoke_e2e.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$scriptDir = $PSScriptRoot
$total = 0

Write-Host "=== AI Assurance E2E Smoke (wrapper) ===" -ForegroundColor Cyan
Write-Host ""

# --- Engine API ------------------------------------------------------------
Write-Host "--- Running smoke_api.ps1 ---" -ForegroundColor Cyan
pwsh -NoProfile -File (Join-Path $scriptDir "smoke_api.ps1")
$apiExit = $LASTEXITCODE
$total += $apiExit
Write-Host ""

# --- Team Workspace SPA ---------------------------------------------------
Write-Host "--- Running smoke_portal.ps1 ---" -ForegroundColor Cyan
pwsh -NoProfile -File (Join-Path $scriptDir "smoke_portal.ps1")
$portalExit = $LASTEXITCODE
$total += $portalExit
Write-Host ""

# --- CISO Console SPA -----------------------------------------------------
Write-Host "--- Running smoke_gov.ps1 ---" -ForegroundColor Cyan
pwsh -NoProfile -File (Join-Path $scriptDir "smoke_gov.ps1")
$govExit = $LASTEXITCODE
$total += $govExit
Write-Host ""

# --- Summary --------------------------------------------------------------
Write-Host "=== Aggregate ===" -ForegroundColor Cyan
Write-Host ("  smoke_api.ps1     exit {0}" -f $apiExit)
Write-Host ("  smoke_portal.ps1  exit {0}" -f $portalExit)
Write-Host ("  smoke_gov.ps1     exit {0}" -f $govExit)
Write-Host ""

if ($total -eq 0) {
    Write-Host "=== SMOKE E2E PASSED — all three scripts exited 0 ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SMOKE E2E FAILED — aggregate exit $total ===" -ForegroundColor Red
    exit $total
}
