# Master orchestrator for AI Assurance Platform deploy.
# Idempotent — safe to re-run. Steps that have already happened are skipped.
#
# Usage:
#   pwsh deploy/deploy-all.ps1                # full deploy + custom domain
#   pwsh deploy/deploy-all.ps1 -Rotate        # regenerate demo passwords
#   pwsh deploy/deploy-all.ps1 -SkipDomain    # skip custom domain steps
#   pwsh deploy/deploy-all.ps1 -SkipDeploy    # only run custom domain / SSL steps
#   pwsh deploy/deploy-all.ps1 -DomainOnly    # alias for -SkipDeploy
#
# Prereqs:
#   - az logged in
#   - .env in repo root with ANTHROPIC_API_KEY, OPENAI_API_KEY, LANGFUSE_*, GODADDY_API_KEY, GODADDY_API_SECRET

param(
    [switch] $Rotate,
    [switch] $SkipDomain,
    [switch] $SkipDeploy,
    [switch] $DomainOnly
)

if ($DomainOnly) { $SkipDeploy = $true }

$ErrorActionPreference = "Stop"
$env:MSYS_NO_PATHCONV = "1"

$ROOT = Split-Path -Parent $PSScriptRoot
$DEPLOY = $PSScriptRoot

# ---- Config -----------------------------------------------------------------
$SUB        = "SignalLayerDev"
$RG         = "rg-aigovern-dev"
$PLAN       = "asp-aigovern-dev"
$APP        = "app-aigovern-dev"
$LOCATION   = "eastus"
$LOCATION_FALLBACKS = @("westus2", "eastus2", "westeurope")
$RUNTIME    = "PYTHON:3.12"
$SKU        = "P1V3"
$STARTUP    = "gunicorn --bind=0.0.0.0:8000 --workers 2 --timeout 120 -k uvicorn.workers.UvicornWorker dashboard:app"
$ZONE       = "sandboxhub.co"
$HOSTLABEL  = "aigovern"
$FQDN       = "$HOSTLABEL.$ZONE"
$DEFAULTFQDN = "$APP.azurewebsites.net"

function Step($n, $msg) { Write-Host "`n[$n] $msg" -ForegroundColor Cyan }
function OK($msg)       { Write-Host "    OK  $msg" -ForegroundColor Green }
function Info($msg)     { Write-Host "    --  $msg" -ForegroundColor Gray }
function Fail($msg)     { Write-Host "    !!  $msg" -ForegroundColor Red; exit 1 }

# ---- 1. Pre-flight ----------------------------------------------------------
Step 1 "Verifying subscription + providers"
az account set --subscription $SUB | Out-Null
$current = az account show --query name -o tsv
if ($current -ne $SUB) { Fail "subscription mismatch: $current" }
OK "subscription = $SUB"

foreach ($p in @("Microsoft.Web", "Microsoft.Insights")) {
    $state = az provider show --namespace $p --query registrationState -o tsv 2>$null
    if ($state -ne "Registered") {
        Info "registering $p"
        az provider register --namespace $p --wait | Out-Null
    }
}
OK "providers registered"

# ---- 2. Resource group ------------------------------------------------------
if (-not $SkipDeploy) {
    Step 2 "Resource group"
    $exists = az group exists --name $RG -o tsv
    if ($exists -eq "true") {
        OK "$RG already exists"
    } else {
        az group create --name $RG --location $LOCATION -o none
        OK "created $RG in $LOCATION"
    }

    # ---- 3. App Service Plan ------------------------------------------------
    Step 3 "App Service plan"
    $planSku = az appservice plan show --name $PLAN --resource-group $RG --query sku.name -o tsv 2>$null
    if ($planSku) {
        OK "$PLAN exists (SKU=$planSku)"
        $tierOrder = @{ "F1"=0; "D1"=0; "B1"=1; "B2"=1; "B3"=1; "S1"=2; "S2"=2; "S3"=2; "P1V3"=3; "P2V3"=3; "P3V3"=3 }
        $current = $tierOrder[$planSku.ToUpper()]
        $target  = $tierOrder[$SKU.ToUpper()]
        if ($null -eq $current -or $current -lt $target) {
            Info "scaling $planSku -> $SKU (deploy reliability on Linux Python needs P1V3+)"
            az appservice plan update --name $PLAN --resource-group $RG --sku $SKU -o none
            OK "scaled to $SKU"
        }
    } else {
        $regions = @($LOCATION) + $LOCATION_FALLBACKS
        $created = $false
        foreach ($loc in $regions) {
            Info "trying $loc..."
            az appservice plan create --name $PLAN --resource-group $RG --location $loc --sku $SKU --is-linux -o none 2>$null
            if ($LASTEXITCODE -eq 0) {
                OK "created $PLAN in $loc (SKU=$SKU)"
                $created = $true
                break
            }
        }
        if (-not $created) { Fail "could not provision plan in any region" }
    }

    # ---- 4. Web App ---------------------------------------------------------
    Step 4 "Web App"
    $appState = az webapp show --name $APP --resource-group $RG --query state -o tsv 2>$null
    if ($appState) {
        OK "$APP exists (state=$appState)"
    } else {
        az webapp create --name $APP --resource-group $RG --plan $PLAN --runtime $RUNTIME -o none
        OK "created $APP"
    }

    # ---- 5. App settings ----------------------------------------------------
    Step 5 "App settings (Oryx + startup + health check)"
    az webapp config appsettings set --name $APP --resource-group $RG --settings `
        SCM_DO_BUILD_DURING_DEPLOYMENT=true `
        ENABLE_ORYX_BUILD=true `
        WEBSITES_PORT=8000 `
        WEBSITE_HTTPLOGGING_RETENTION_DAYS=3 `
        PYTHON_ENABLE_GUNICORN_MULTIWORKERS=true -o none
    OK "Oryx flags set"

    az webapp config set --name $APP --resource-group $RG --startup-file $STARTUP -o none
    OK "startup command set"

    $healthFile = "$DEPLOY\health-config.json"
    if (-not (Test-Path $healthFile)) { '{"healthCheckPath": "/api/health"}' | Out-File -FilePath $healthFile -Encoding ASCII }
    az webapp config set --name $APP --resource-group $RG --generic-configurations "@$healthFile" -o none
    OK "health check path = /api/health"

    # ---- 6. Demo credentials -----------------------------------------------
    Step 6 "Demo credentials"
    if ($Rotate) {
        python "$DEPLOY\generate-creds.py" --rotate
    } else {
        python "$DEPLOY\generate-creds.py"
    }

    az webapp config appsettings set --name $APP --resource-group $RG --settings "@$DEPLOY\appsettings.json" -o none
    OK "demo user hashes + SESSION_SECRET pushed"

    # ---- 7. Runtime secrets from .env --------------------------------------
    Step 7 "Runtime secrets from .env"
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$DEPLOY\push-secrets.ps1"
    if ($LASTEXITCODE -ne 0) { Fail "push-secrets failed" }

    # ---- 8. Build zip -------------------------------------------------------
    Step 8 "Build deploy zip"
    python "$DEPLOY\build-zip.py"
    if (-not (Test-Path "$DEPLOY\app.zip")) { Fail "app.zip not built" }

    # ---- 9. Static import check --------------------------------------------
    Step 9 "Static import check (catch missing deps before deploy)"
    python "$DEPLOY\check-imports.py"
    if ($LASTEXITCODE -ne 0) { Fail "missing top-level deps in zip — fix before deploy" }

    # ---- 10. Deploy zip -----------------------------------------------------
    Step 10 "Deploying zip (using Kudu config-zip for reliable polling)"
    az webapp deployment source config-zip --name $APP --resource-group $RG --src "$DEPLOY\app.zip" --timeout 1200 2>&1 | Out-Null
    Info "upload submitted; polling Kudu deployment list..."

    $deployOk = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 10
        $row = az webapp log deployment list --name $APP --resource-group $RG --query "[0].{id:id, status:status, end:end_time}" -o json 2>$null | ConvertFrom-Json
        if ($row) {
            $tag = $row.id.Substring(0, 8)
            Info "[$i] deploy=$tag status=$($row.status)"
            if ($row.status -eq 4) { $deployOk = $true; break }
            if ($row.status -eq 3) { Fail "deploy failed (status=3) for $tag" }
        }
    }
    if (-not $deployOk) { Fail "deploy polling timed out" }
    OK "deploy succeeded"

    # ---- 11. Wait for app warm-up ------------------------------------------
    Step 11 "Waiting for /api/health to return 200"
    $healthy = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 10
        $code = curl.exe -s -o NUL -w "%{http_code}" "https://$DEFAULTFQDN/api/health"
        if ($code -eq "200") { $healthy = $true; OK "/api/health -> 200"; break }
        if (($i % 6) -eq 0) { Info "[$i] /api/health -> $code (still warming)" }
    }
    if (-not $healthy) { Fail "app never reached 200 — check docker logs" }

    # ---- 12. Smoke test login flow -----------------------------------------
    Step 12 "Smoke testing auth gate"
    $r302 = curl.exe -s -o NUL -w "%{http_code}" "https://$DEFAULTFQDN/"
    $r401 = curl.exe -s -o NUL -w "%{http_code}" "https://$DEFAULTFQDN/api/grc/ai-systems"
    if ($r302 -eq "302" -and $r401 -eq "401") {
        OK "auth gate: / -> 302, /api/* -> 401"
    } else {
        Fail "auth gate misconfigured: / -> $r302, /api/* -> $r401"
    }
}
else {
    Step "1-12" "SKIPPED (deploy)"
}

# ---- 13. Custom domain + SSL ------------------------------------------------
if (-not $SkipDomain) {
    Step 13 "Custom domain: $FQDN"

    $asuid = az webapp show --name $APP --resource-group $RG --query customDomainVerificationId -o tsv
    if (-not $asuid) { Fail "could not read customDomainVerificationId" }
    Info "verification id = $($asuid.Substring(0,8))..."

    # GoDaddy DNS records (idempotent PUT)
    Info "GoDaddy: CNAME $HOSTLABEL.$ZONE -> $DEFAULTFQDN"
    python "$DEPLOY\godaddy-dns.py" upsert --domain $ZONE --type CNAME --name $HOSTLABEL --data $DEFAULTFQDN
    if ($LASTEXITCODE -ne 0) { Fail "GoDaddy CNAME upsert failed" }

    Info "GoDaddy: TXT asuid.$HOSTLABEL.$ZONE -> <verificationId>"
    python "$DEPLOY\godaddy-dns.py" upsert --domain $ZONE --type TXT --name "asuid.$HOSTLABEL" --data $asuid
    if ($LASTEXITCODE -ne 0) { Fail "GoDaddy TXT upsert failed" }

    Info "Waiting for DNS to propagate (up to 10 min)..."
    python "$DEPLOY\godaddy-dns.py" wait --fqdn $FQDN --expect $DEFAULTFQDN --timeout 600
    if ($LASTEXITCODE -ne 0) { Fail "DNS never propagated" }
    OK "DNS resolves"

    # Bind hostname
    $bound = az webapp config hostname list --webapp-name $APP --resource-group $RG --query "[?name=='$FQDN'].name" -o tsv 2>$null
    if ($bound) {
        OK "hostname $FQDN already bound"
    } else {
        Info "binding hostname (validates DNS records)..."
        az webapp config hostname add --webapp-name $APP --resource-group $RG --hostname $FQDN -o none
        OK "hostname bound"
    }

    # Managed cert + SSL bind
    $tp = az webapp config ssl list --resource-group $RG --query "[?subjectName=='$FQDN'].thumbprint | [0]" -o tsv 2>$null
    if (-not $tp) {
        Info "issuing free App Service Managed Certificate..."
        az webapp config ssl create --hostname $FQDN --name $APP --resource-group $RG -o none
        Start-Sleep -Seconds 10
        $tp = az webapp config ssl list --resource-group $RG --query "[?subjectName=='$FQDN'].thumbprint | [0]" -o tsv
    }
    if (-not $tp) { Fail "could not obtain managed certificate" }
    OK "cert thumbprint = $($tp.Substring(0,12))..."

    $sslState = az webapp config hostname list --webapp-name $APP --resource-group $RG --query "[?name=='$FQDN'].sslState | [0]" -o tsv
    if ($sslState -eq "SniEnabled") {
        OK "SSL already bound (SNI)"
    } else {
        az webapp config ssl bind --certificate-thumbprint $tp --ssl-type SNI --name $APP --resource-group $RG -o none
        OK "SSL bound (SNI)"
    }

    # ---- 14. Probe custom domain ------------------------------------------
    Step 14 "Probing custom domain HTTPS"
    $code = curl.exe -s -o NUL -w "%{http_code}" "https://$FQDN/api/health"
    if ($code -eq "200") {
        OK "https://$FQDN/api/health -> 200"
    } else {
        Info "https://$FQDN/api/health -> $code (cert may still be issuing; retry in 1-2 min)"
    }
}
else {
    Step "13-14" "SKIPPED (domain)"
}

# ---- 15. Final summary ------------------------------------------------------
Step 15 "Done"
Write-Host ""
Write-Host "  Default URL:  https://$DEFAULTFQDN" -ForegroundColor Green
Write-Host "  Custom URL:   https://$FQDN" -ForegroundColor Green
Write-Host ""
Write-Host "  Credentials saved at: $DEPLOY\creds.txt (gitignored)" -ForegroundColor Gray
Write-Host ""
