# Test-VendorRisk.ps1 — CLI demo backup for the vendor_risk agent.
#
# Wraps `python -m agents.vendor_risk.eval.run_calibration --case <id>` so a
# demo can fall back to the terminal if the Agent Runner SPA stutters.
#
# Prerequisites:
#   $env:AIGOVERN_BASE_URL = "https://aigovern.sandboxhub.co"
#   $env:AIGOVERN_COOKIE   = "aigovern_session=<paste fresh demo-ciso cookie>"
#
# Usage:
#   .\scripts\Test-VendorRisk.ps1 ext-05-edge-carveout-eu
#   .\scripts\Test-VendorRisk.ps1 int-02-mnpi-active-deal
#   .\scripts\Test-VendorRisk.ps1 -List               # show all fixture IDs
#   .\scripts\Test-VendorRisk.ps1 -DryRun ext-08-...  # plan only
#
# Note: for INT scenarios, the harness PATCHes runtime-flags pre-flight
# automatically — no extra step needed if the cookie's session has the
# `ciso` or `tprm-analyst` role.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string] $CaseId,

    [switch] $List,

    [switch] $DryRun
)

$ErrorActionPreference = 'Stop'

# Resolve project root: this script lives in scripts/, so root is parent.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir

if ($List) {
    $ExtPath = Join-Path $RepoRoot 'agents\vendor_risk\eval\dataset-external.jsonl'
    $IntPath = Join-Path $RepoRoot 'agents\vendor_risk\eval\dataset-internal.jsonl'
    Write-Host ""
    Write-Host "EXT fixtures (sys-vendor-risk-ext-001):" -ForegroundColor Cyan
    Get-Content $ExtPath | ForEach-Object {
        $row = $_ | ConvertFrom-Json
        $line = "  {0,-36} -> {1,-8}  {2}" -f $row.id, $row.expected_risk_tier, $row.label
        Write-Host $line
    }
    Write-Host ""
    Write-Host "INT fixtures (sys-vendor-risk-int-001):" -ForegroundColor Cyan
    Get-Content $IntPath | ForEach-Object {
        $row = $_ | ConvertFrom-Json
        $line = "  {0,-36} -> {1,-8}  {2}" -f $row.id, $row.expected_risk_tier, $row.label
        Write-Host $line
    }
    Write-Host ""
    return
}

if (-not $CaseId) {
    Write-Host "Usage: .\Test-VendorRisk.ps1 <fixture-id>  |  -List  |  -DryRun <fixture-id>" -ForegroundColor Yellow
    Write-Host "Example: .\Test-VendorRisk.ps1 ext-05-edge-carveout-eu"
    return
}

if (-not $env:AIGOVERN_BASE_URL) {
    Write-Error "AIGOVERN_BASE_URL is not set. Run: `$env:AIGOVERN_BASE_URL = 'https://aigovern.sandboxhub.co'"
    return
}
if (-not $env:AIGOVERN_COOKIE) {
    Write-Error "AIGOVERN_COOKIE is not set. Paste a fresh demo-ciso cookie: `$env:AIGOVERN_COOKIE = 'aigovern_session=...'"
    return
}

if ($DryRun) {
    $env:DRY_RUN = '1'
} else {
    Remove-Item Env:DRY_RUN -ErrorAction SilentlyContinue
}

Push-Location $RepoRoot
try {
    Write-Host ""
    Write-Host "Driving vendor_risk against $CaseId ..." -ForegroundColor Cyan
    Write-Host "  base_url: $env:AIGOVERN_BASE_URL"
    Write-Host "  dry_run : $($DryRun.IsPresent)"
    Write-Host ""
    python -m agents.vendor_risk.eval.run_calibration --case $CaseId
    $exitCode = $LASTEXITCODE
    Write-Host ""
    if ($exitCode -eq 0) {
        Write-Host "OK — exit $exitCode" -ForegroundColor Green
    } else {
        Write-Host "FAIL — exit $exitCode" -ForegroundColor Red
    }
} finally {
    Pop-Location
}
