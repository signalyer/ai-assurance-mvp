# Provisions api.aigovern.sandboxhub.co on the existing App Service.
#
# Per docs/plans/SESSION-13-v2-engine-hardening.md §3.A4 + V2-PORTAL-SPLIT.md §5.
#
# Two-phase flow (split because Azure cert issuance requires CNAME propagation):
#   Phase 1: create CNAME via GoDaddy API
#   ----- wait 5-10 min for DNS propagation -----
#   Phase 2: bind custom hostname + create + bind managed cert in Azure
#
# Prereqs (set as env vars before invoking):
#   $env:GODADDY_API_KEY     = "<key>"
#   $env:GODADDY_API_SECRET  = "<secret>"
#   az login + az account set --subscription "SignalLayerDev" (already active)
#
# Usage:
#   pwsh deploy/bind-api-subdomain.ps1                  # both phases (auto-waits)
#   pwsh deploy/bind-api-subdomain.ps1 -Phase Dns       # only Phase 1
#   pwsh deploy/bind-api-subdomain.ps1 -Phase Bind      # only Phase 2 (skip DNS)
#   pwsh deploy/bind-api-subdomain.ps1 -DryRun          # print actions, don't execute
#
# Idempotent: re-running is safe -- existing records / bindings are detected
# and skipped with a green message.

param(
    [ValidateSet("Both", "Dns", "Bind")]
    [string]$Phase = "Both",

    [switch]$DryRun,

    [int]$PropagationWaitSeconds = 300,

    [string]$ApexDomain   = "sandboxhub.co",
    [string]$Subdomain    = "api.aigovern",
    [string]$AppServiceName = "app-aigovern-dev",
    [string]$ResourceGroup  = "rg-aigovern-dev"
)

$ErrorActionPreference = "Stop"
$env:MSYS_NO_PATHCONV  = "1"   # Windows Git Bash path-fix (CLAUDE.md global rule)

$FullHostname  = "$Subdomain.$ApexDomain"                                      # api.aigovern.sandboxhub.co
$CnameTarget   = "$AppServiceName.azurewebsites.net"                           # app-aigovern-dev.azurewebsites.net
$RecordType    = "CNAME"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Bind $FullHostname -> $CnameTarget" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# Phase 1: GoDaddy CNAME via API
# ---------------------------------------------------------------------------

function Invoke-GoDaddyPhase {
    if (-not $env:GODADDY_API_KEY -or -not $env:GODADDY_API_SECRET) {
        throw "Missing env vars. Set GODADDY_API_KEY + GODADDY_API_SECRET (get from https://developer.godaddy.com/keys -- use Production keys, NOT OTE)."
    }

    $authHeader = @{
        "Authorization" = "sso-key $($env:GODADDY_API_KEY):$($env:GODADDY_API_SECRET)"
        "Content-Type"  = "application/json"
    }

    # Check existing record first (idempotency)
    $checkUri = "https://api.godaddy.com/v1/domains/$ApexDomain/records/$RecordType/$Subdomain"
    Write-Host "[1/3] Checking existing $RecordType record at $checkUri" -ForegroundColor Yellow
    try {
        $existing = Invoke-RestMethod -Uri $checkUri -Headers $authHeader -Method Get
        if ($existing -and $existing.Count -gt 0 -and $existing[0].data -eq $CnameTarget) {
            Write-Host "  -> EXISTS and matches ($($existing[0].data)). Skipping create." -ForegroundColor Green
            return
        }
        if ($existing -and $existing.Count -gt 0) {
            Write-Host "  -> EXISTS but points to wrong target: $($existing[0].data). Will overwrite." -ForegroundColor Yellow
        }
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) {
            throw "GoDaddy API check failed: $($_.Exception.Message)"
        }
        Write-Host "  -> No existing record (404). Will create." -ForegroundColor Yellow
    }

    # PUT replaces all records of this type+name with the body we provide.
    $putUri = "https://api.godaddy.com/v1/domains/$ApexDomain/records/$RecordType/$Subdomain"
    $body = @(@{
        data = $CnameTarget
        ttl  = 600
    }) | ConvertTo-Json -AsArray

    if ($DryRun) {
        Write-Host "[2/3] DRY-RUN -- would PUT $putUri" -ForegroundColor Magenta
        Write-Host "       body: $body"
        return
    }

    Write-Host "[2/3] PUT $putUri" -ForegroundColor Yellow
    Invoke-RestMethod -Uri $putUri -Headers $authHeader -Method Put -Body $body | Out-Null
    Write-Host "  -> Created CNAME $FullHostname -> $CnameTarget" -ForegroundColor Green

    # Verify (DNS query through public resolver may lag GoDaddy's API by a few sec)
    Write-Host "[3/3] Verifying via GoDaddy API readback..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    $readback = Invoke-RestMethod -Uri $checkUri -Headers $authHeader -Method Get
    if ($readback -and $readback[0].data -eq $CnameTarget) {
        Write-Host "  -> CONFIRMED: GoDaddy API reports $RecordType $FullHostname = $($readback[0].data)" -ForegroundColor Green
    }
    else {
        Write-Warning "Readback mismatch; manual verification recommended."
    }
}

# ---------------------------------------------------------------------------
# Phase 2: Azure custom domain + managed cert
# ---------------------------------------------------------------------------

function Invoke-AzurePhase {
    # Confirm subscription
    $sub = az account show --query "name" -o tsv
    if ($sub -ne "SignalLayerDev") {
        throw "Wrong Azure subscription. Active: '$sub'. Expected: 'SignalLayerDev'. Run: az account set --subscription 'SignalLayerDev'"
    }

    # Check if hostname already bound
    Write-Host "[1/4] Checking existing hostname binding on $AppServiceName..." -ForegroundColor Yellow
    $existing = az webapp config hostname list --webapp-name $AppServiceName --resource-group $ResourceGroup `
        --query "[?name=='$FullHostname']" -o json | ConvertFrom-Json
    if ($existing -and $existing.Count -gt 0) {
        Write-Host "  -> Hostname $FullHostname ALREADY BOUND. Will check SSL." -ForegroundColor Green
        $sslState = $existing[0].sslState
        $thumb = $existing[0].thumbprint
        if ($sslState -eq "SniEnabled" -and $thumb) {
            Write-Host "  -> SSL ALREADY BOUND (thumb=$thumb). Phase 2 complete." -ForegroundColor Green
            return
        }
        Write-Host "  -> Hostname bound but SSL not yet. Continuing to cert step." -ForegroundColor Yellow
    }
    else {
        if ($DryRun) {
            Write-Host "[2/4] DRY-RUN -- would: az webapp config hostname add --webapp-name $AppServiceName -g $ResourceGroup --hostname $FullHostname" -ForegroundColor Magenta
        }
        else {
            Write-Host "[2/4] Adding custom hostname binding..." -ForegroundColor Yellow
            az webapp config hostname add `
                --webapp-name $AppServiceName `
                --resource-group $ResourceGroup `
                --hostname $FullHostname | Out-Null
            Write-Host "  -> Hostname $FullHostname bound (HTTP only, no SSL yet)." -ForegroundColor Green
        }
    }

    if ($DryRun) {
        Write-Host "[3/4] DRY-RUN -- would: az webapp config ssl create --hostname $FullHostname --name $AppServiceName -g $ResourceGroup" -ForegroundColor Magenta
        Write-Host "[4/4] DRY-RUN -- would: az webapp config ssl bind ..." -ForegroundColor Magenta
        return
    }

    Write-Host "[3/4] Provisioning App Service Managed Certificate (free; P2v3 supports)..." -ForegroundColor Yellow
    $certJson = az webapp config ssl create `
        --hostname $FullHostname `
        --name $AppServiceName `
        --resource-group $ResourceGroup 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        throw "Cert creation failed: $certJson"
    }
    Write-Host "  -> Managed cert issued." -ForegroundColor Green

    # Extract thumbprint from the create-call output (most reliable).
    # `az webapp config ssl list` does NOT see Microsoft.Web/certificates
    # resources -- use `az resource list` as the fallback.
    $thumb = $null
    try {
        $cert = $certJson | ConvertFrom-Json
        # The create response is the parent webapp object with `properties.hostNameSslStates`
        # or, if returned directly, the cert object with thumbprint at top level
        if ($cert.thumbprint) { $thumb = $cert.thumbprint }
        elseif ($cert.properties.thumbprint) { $thumb = $cert.properties.thumbprint }
    }
    catch { } # JSON may be wrapped or noisy; fall through to resource-list lookup

    if (-not $thumb) {
        $thumb = az resource list --resource-group $ResourceGroup `
            --resource-type "Microsoft.Web/certificates" `
            --query "[?properties.subjectName=='$FullHostname'].properties.thumbprint | [0]" -o tsv
    }
    if (-not $thumb) {
        throw "Could not find thumbprint for $FullHostname after cert creation. Run: az resource list -g $ResourceGroup --resource-type Microsoft.Web/certificates"
    }
    Write-Host "  -> Cert thumbprint: $thumb"

    Write-Host "[4/4] Binding cert to hostname (SNI)..." -ForegroundColor Yellow
    az webapp config ssl bind `
        --certificate-thumbprint $thumb `
        --ssl-type SNI `
        --name $AppServiceName `
        --resource-group $ResourceGroup `
        --hostname $FullHostname | Out-Null

    Write-Host "  -> SSL bound. Verifying..." -ForegroundColor Green
    $health = Invoke-WebRequest -Uri "https://$FullHostname/api/health" -UseBasicParsing -ErrorAction SilentlyContinue
    if ($health.StatusCode -eq 200) {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Green
        Write-Host "  SUCCESS: https://$FullHostname/api/health returns 200" -ForegroundColor Green
        Write-Host "============================================================" -ForegroundColor Green
    }
    else {
        Write-Warning "Bound but health probe didn't return 200 (got $($health.StatusCode)). May need a minute for App Service to recognise."
    }
}

# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

if ($Phase -eq "Both" -or $Phase -eq "Dns") {
    Invoke-GoDaddyPhase
}

if ($Phase -eq "Both") {
    Write-Host ""
    Write-Host "Waiting $PropagationWaitSeconds seconds for DNS propagation before Azure binding..." -ForegroundColor Yellow
    Write-Host "  (cancel with Ctrl-C and re-run with -Phase Bind once you've verified propagation manually)"
    Start-Sleep -Seconds $PropagationWaitSeconds
}

if ($Phase -eq "Both" -or $Phase -eq "Bind") {
    Invoke-AzurePhase
}

Write-Host ""
Write-Host "Done." -ForegroundColor Cyan
