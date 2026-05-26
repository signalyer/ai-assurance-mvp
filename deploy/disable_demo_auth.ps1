<#
.SYNOPSIS
    S50 STEP 5 — One-way cutover script that disables the bcrypt demo-auth
    path on the AI Assurance engine. After this lands, Microsoft Entra OIDC
    is the only path to a valid session cookie.

.DESCRIPTION
    Flips ALLOW_DEMO_AUTH=false on BOTH the production slot and the staging
    slot of app-aigovern-dev. The script is the only sanctioned way to do
    the flip — running az commands by hand risks forgetting the staging
    slot and leaving a live bcrypt door open on a publicly-reachable URL.

    Default mode is DRY RUN: prints the current value on each slot, prints
    the value it WOULD set, prints what the smoke validation would look
    like, and exits without touching App Service. To actually apply, pass
    -Apply. Even with -Apply, the script prompts for explicit confirmation
    before mutating anything.

    Post-mutation, the script:
      1. waits ~45s for each slot's container to recycle
      2. polls /api/auth/config on each slot until allow_demo_auth=false
         (or 90s timeout)
      3. exits 0 only when both slots return allow_demo_auth=false

    This script does NOT (and must not) reverse direction. ADR-002 §6
    declared the cutover one-way to remove the bcrypt attack surface
    once Entra OIDC is the production auth path. Re-enabling demo auth
    after a cutover should be an explicit, audited operator action —
    not a flag flip in a routine deploy script.

.PARAMETER Apply
    Required to perform the actual mutation. Without -Apply the script
    only reports.

.EXAMPLE
    # Inspect current state without changing anything (default):
    pwsh deploy/disable_demo_auth.ps1

.EXAMPLE
    # Perform the cutover (will prompt for confirmation):
    pwsh deploy/disable_demo_auth.ps1 -Apply
#>

[CmdletBinding()]
param(
    [switch]$Apply
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$AppName       = "app-aigovern-dev"
$ResourceGroup = "rg-aigovern-dev"
$StagingSlot   = "staging"

# Production = the default slot (root URL); staging = the slot-specific URL.
# Each gets its own /api/auth/config probe.
$ProdAuthConfig    = "https://aigovern.sandboxhub.co/api/auth/config"
$StagingAuthConfig = "https://$AppName-staging.azurewebsites.net/api/auth/config"

$TargetValue = "false"
$SettingName = "ALLOW_DEMO_AUTH"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Get-Setting {
    param(
        [Parameter(Mandatory)] [string]$Slot  # "production" or the staging slot name
    )
    $slotArgs = if ($Slot -eq "production") { @() } else { @("--slot", $Slot) }
    $val = az webapp config appsettings list `
        --name $AppName `
        --resource-group $ResourceGroup `
        @slotArgs `
        --query "[?name=='$SettingName'].value | [0]" `
        -o tsv 2>$null
    if (-not $val) { return "<unset>" }
    return $val
}

function Set-Setting {
    param(
        [Parameter(Mandatory)] [string]$Slot,
        [Parameter(Mandatory)] [string]$Value
    )
    $slotArgs = if ($Slot -eq "production") { @() } else { @("--slot", $Slot) }
    az webapp config appsettings set `
        --name $AppName `
        --resource-group $ResourceGroup `
        @slotArgs `
        --settings "$SettingName=$Value" `
        -o none
}

function Wait-Flag-False {
    param(
        [Parameter(Mandatory)] [string]$ConfigUrl,
        [Parameter(Mandatory)] [string]$Label,
        [int]$TimeoutSec = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $ConfigUrl -Method GET -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                $json = "$($resp.Content)" | ConvertFrom-Json
                if ($json.PSObject.Properties['allow_demo_auth'] -and $json.allow_demo_auth -eq $false) {
                    Write-Host "  ✔ $Label : allow_demo_auth=false confirmed" -ForegroundColor Green
                    return $true
                }
            }
        } catch {
            # transient — container may still be restarting
        }
        Start-Sleep -Seconds 5
    }
    Write-Host "  ✘ $Label : timed out waiting for allow_demo_auth=false" -ForegroundColor Red
    return $false
}

# ---------------------------------------------------------------------------
# Pre-flight: show current state on both slots
# ---------------------------------------------------------------------------

Write-Host "=== S50 STEP 5 — Disable Demo Auth (ALLOW_DEMO_AUTH=false) ===" -ForegroundColor Cyan
Write-Host "App Service:   $AppName / $ResourceGroup"
Write-Host "Mode:          $(if ($Apply) { 'APPLY' } else { 'DRY RUN (pass -Apply to mutate)' })"
Write-Host ""

Write-Host "Reading current state..." -ForegroundColor Yellow
$prodNow    = Get-Setting -Slot "production"
$stagingNow = Get-Setting -Slot $StagingSlot

Write-Host ("  production : ALLOW_DEMO_AUTH = {0}" -f $prodNow)
Write-Host ("  staging    : ALLOW_DEMO_AUTH = {0}" -f $stagingNow)
Write-Host ""

if ($prodNow -eq $TargetValue -and $stagingNow -eq $TargetValue) {
    Write-Host "Both slots already at ALLOW_DEMO_AUTH=$TargetValue — nothing to do." -ForegroundColor Green
    exit 0
}

Write-Host ("Planned change : ALLOW_DEMO_AUTH = {0}  →  {1}  (both slots)" -f $prodNow, $TargetValue) -ForegroundColor Yellow
Write-Host ""

if (-not $Apply) {
    Write-Host "DRY RUN — no changes made. Re-run with -Apply to perform the cutover." -ForegroundColor DarkYellow
    Write-Host "Post-apply verification will probe:" -ForegroundColor DarkGray
    Write-Host "  $ProdAuthConfig" -ForegroundColor DarkGray
    Write-Host "  $StagingAuthConfig" -ForegroundColor DarkGray
    exit 0
}

# ---------------------------------------------------------------------------
# Apply path — confirmation gate
# ---------------------------------------------------------------------------

Write-Host "This is a ONE-WAY cutover (ADR-002 §6). After it lands, the bcrypt" -ForegroundColor Yellow
Write-Host "demo accounts (demo-ciso, demo-engineer, etc.) can no longer sign in." -ForegroundColor Yellow
Write-Host "Microsoft Entra OIDC becomes the only auth path on both slots." -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "Type 'cutover' to proceed"
if ($confirm -ne "cutover") {
    Write-Host "Confirmation not given — aborting." -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# Mutate both slots
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Applying to staging slot..." -ForegroundColor Cyan
Set-Setting -Slot $StagingSlot -Value $TargetValue
Write-Host "  ✔ staging app-setting written"

Write-Host "Applying to production slot..." -ForegroundColor Cyan
Set-Setting -Slot "production" -Value $TargetValue
Write-Host "  ✔ production app-setting written"

# ---------------------------------------------------------------------------
# Wait for container recycle + verify
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "Waiting ~45s for App Service slots to recycle..." -ForegroundColor Yellow
Start-Sleep -Seconds 45

Write-Host "Verifying staging..."
$stagingOk = Wait-Flag-False -ConfigUrl $StagingAuthConfig -Label "staging"

Write-Host "Verifying production..."
$prodOk = Wait-Flag-False -ConfigUrl $ProdAuthConfig -Label "production"

Write-Host ""
if ($stagingOk -and $prodOk) {
    Write-Host "=== CUTOVER COMPLETE — bcrypt demo auth disabled on both slots ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== CUTOVER PARTIAL — verify each slot's /api/auth/config manually before declaring done ===" -ForegroundColor Red
    exit 2
}
