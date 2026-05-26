<#
.SYNOPSIS
    CISO Console SPA smoke test — verifies the V2 governance portal SPA loads.
    Session 44 split from the engine-side smoke_api.ps1.

.DESCRIPTION
    Until Session 45 DNS cutover, the target is the staging hostname
    swa-aigovern-gov-dev.azurestaticapps.net. At cutover, set
    $env:SMOKE_GOV_URL = "https://gov.aigovern.sandboxhub.co/" and the same
    script verifies the custom-DNS host.

    Probes mirror smoke_portal.ps1 — same five-probe shape, different role
    (demo-ciso) and authed endpoint (/api/v1/grc/policies).

      1. Index HTML reachable
      2. JS bundle reachable
      3. CSS reachable (or SKIP)
      4. Subroute SPA fallback — GET /findings returns 200 + SPA shell
         (S48 / S47 #1 compound rule)
      5. Authenticated API — login demo-ciso → GET /grc/policies returns 200
         (SKIPS if $env:SMOKE_DEMO_PASSWORD_CISO is unset)

    V2-PORTAL-SPLIT §A5 acceptance: this script exits 0.

    Required env vars for full coverage:
      SMOKE_DEMO_PASSWORD_CISO  — demo-ciso password (1Password)
    Optional:
      SMOKE_GOV_URL, SMOKE_API_URL, SMOKE_GOV_SUBROUTE, SMOKE_DEMO_USER_CISO

    Exit codes:
      0 — all probes pass
      N — count of failing probes

.EXAMPLE
    # Production (post-S45 cutover) with full auth coverage:
    $env:SMOKE_GOV_URL = "https://gov.aigovern.sandboxhub.co/"
    $env:SMOKE_DEMO_PASSWORD_CISO = (op read "op://SignalLayer/aigovern-demo/ciso-password")
    pwsh deploy/smoke_gov.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$BaseUrl = if ($env:SMOKE_GOV_URL) {
    $env:SMOKE_GOV_URL.TrimEnd('/')
} else {
    "https://swa-aigovern-gov-dev.azurestaticapps.net"
}

# Engine API (separate origin — same chain as smoke_portal.ps1).
$ApiBaseUrl = if ($env:SMOKE_API_URL) {
    $env:SMOKE_API_URL.TrimEnd('/')
} else {
    "https://aigovern.sandboxhub.co"
}

# CISO Console subroute probe target.
$SubRoute = if ($env:SMOKE_GOV_SUBROUTE) { $env:SMOKE_GOV_SUBROUTE } else { "/findings" }

# Demo-role credentials (S48 STEP 2; Q2 = 1Password env-vars).
$DemoUser = if ($env:SMOKE_DEMO_USER_CISO) { $env:SMOKE_DEMO_USER_CISO } else { "demo-ciso" }
$DemoPass = $env:SMOKE_DEMO_PASSWORD_CISO

Write-Host "=== AI Assurance CISO Console SPA Smoke (smoke_gov.ps1) ===" -ForegroundColor Cyan
Write-Host "Target:      $BaseUrl"
Write-Host "API:         $ApiBaseUrl"
Write-Host "Subroute:    $SubRoute"
Write-Host "Demo user:   $DemoUser  (password $(if ($DemoPass) { 'set' } else { 'NOT SET — Probes 4-5 will SKIP' }))"
Write-Host ""

$Failures = 0

function Invoke-Probe {
    param([string]$Name, [scriptblock]$ScriptBlock)
    Write-Host "Probe: $Name" -NoNewline
    try {
        & $ScriptBlock
        Write-Host "  [PASS]" -ForegroundColor Green
    } catch {
        $msg = "$_"
        if ($msg -match "refused|unreachable|No connection|Unable to connect|SocketException|actively refused") {
            Write-Host "  [SKIP] target unreachable ($BaseUrl)" -ForegroundColor DarkYellow
        } else {
            Write-Host "  [FAIL] $msg" -ForegroundColor Red
            $script:Failures++
        }
    }
}

# ---------------------------------------------------------------------------
# Probe 1 — Index HTML reachable + Vite shell present
# ---------------------------------------------------------------------------
$indexHtml = $null
Invoke-Probe -Name "1. Index HTML reachable (GET /)" -ScriptBlock {
    $resp = Invoke-WebRequest -Uri "$BaseUrl/" -Method GET -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        throw "Expected HTTP 200; got $($resp.StatusCode)"
    }
    $script:indexHtml = "$($resp.Content)"
    if ($script:indexHtml -notmatch '<div\s+id="app"') {
        throw 'index.html does not contain the SPA root element (<div id="app">) — SPA shell missing'
    }
}

# ---------------------------------------------------------------------------
# Probe 2 — First JS bundle reachable
# ---------------------------------------------------------------------------
Invoke-Probe -Name "2. JS bundle reachable (first <script src=...>)" -ScriptBlock {
    if (-not $script:indexHtml) {
        throw "index.html not loaded — Probe 1 must succeed first"
    }
    if ($script:indexHtml -notmatch '<script[^>]+src="([^"]+\.js)"') {
        throw "No JS bundle referenced in index.html"
    }
    $jsPath = $Matches[1]
    $jsUrl = if ($jsPath -match '^https?://') { $jsPath } else { "$BaseUrl/$($jsPath.TrimStart('/'))" }
    $resp = Invoke-WebRequest -Uri $jsUrl -Method GET -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        throw "JS bundle '$jsUrl' returned HTTP $($resp.StatusCode)"
    }
}

# ---------------------------------------------------------------------------
# Probe 3 — First CSS reachable (optional — Vite may inline CSS)
# ---------------------------------------------------------------------------
Invoke-Probe -Name "3. CSS reachable (first <link rel=stylesheet ...>)" -ScriptBlock {
    if (-not $script:indexHtml) {
        throw "index.html not loaded — Probe 1 must succeed first"
    }
    if ($script:indexHtml -notmatch '<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"') {
        Write-Host " (skipped — CSS inlined by Vite, no <link rel=stylesheet> tag)" -NoNewline -ForegroundColor DarkYellow
        return
    }
    $cssPath = $Matches[1]
    $cssUrl = if ($cssPath -match '^https?://') { $cssPath } else { "$BaseUrl/$($cssPath.TrimStart('/'))" }
    $resp = Invoke-WebRequest -Uri $cssUrl -Method GET -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        throw "CSS '$cssUrl' returned HTTP $($resp.StatusCode)"
    }
}

# ---------------------------------------------------------------------------
# Probe 4 — Subroute returns SPA shell (S47 #1 compound rule)
# ---------------------------------------------------------------------------
Invoke-Probe -Name "4. Subroute SPA fallback (GET $SubRoute → SPA shell)" -ScriptBlock {
    $resp = Invoke-WebRequest -Uri "$BaseUrl$SubRoute" -Method GET -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        throw "Expected HTTP 200; got $($resp.StatusCode) — SPA fallback may be missing (staticwebapp.config.json)"
    }
    $body = "$($resp.Content)"
    if ($body -notmatch '<div\s+id="app"') {
        throw "$SubRoute did not return the SPA shell — likely served a 404 page instead of index.html"
    }
}

# ---------------------------------------------------------------------------
# Probe 5 — Authenticated API probe via cross-subdomain cookie
# Logs in as demo-ciso against the engine, then makes an authed call to
# /api/v1/grc/policies. Verifies the .aigovern.sandboxhub.co cookie chain.
# ---------------------------------------------------------------------------
Invoke-Probe -Name "5. Authenticated API (login as $DemoUser → GET /grc/policies)" -ScriptBlock {
    if (-not $DemoPass) {
        Write-Host " (skipped — `$env:SMOKE_DEMO_PASSWORD_CISO not set)" -NoNewline -ForegroundColor DarkYellow
        return
    }
    $loginBody = @{ username = $DemoUser; password = $DemoPass; next = '/' }
    $loginResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/auth/login" `
        -Method POST `
        -Body $loginBody `
        -SessionVariable smokeSession `
        -MaximumRedirection 0 `
        -SkipHttpErrorCheck `
        -ErrorAction Stop
    if ($loginResp.StatusCode -ne 200 -and $loginResp.StatusCode -ne 302 -and $loginResp.StatusCode -ne 303) {
        throw "Login failed: HTTP $($loginResp.StatusCode)"
    }

    $apiResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/grc/policies" `
        -Method GET `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($apiResp.StatusCode -ne 200) {
        throw "Authed API call returned HTTP $($apiResp.StatusCode) — cookie may not be reaching engine"
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
if ($Failures -eq 0) {
    Write-Host "=== SMOKE GOV PASSED — CISO Console SPA reachable ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SMOKE GOV FAILED — $Failures probe(s) failed ===" -ForegroundColor Red
    exit $Failures
}
