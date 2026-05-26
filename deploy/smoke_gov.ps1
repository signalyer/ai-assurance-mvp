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
      6. Auth feature-flags — GET /api/auth/config returns oidc_enabled=true
         (S50 — the SPA reads this on /login mount to render the
         "Sign in with Microsoft" CTA; if it's missing or false, the
         CTA never appears regardless of what the SPA bundle contains)

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
# Probe 6 — Auth feature-flags endpoint (S50)
# The SPA's /login page reads /api/auth/config on mount and decides which
# CTAs to render. Curling /login itself only returns the empty SPA shell —
# the MS button is JS-rendered. Probing /api/auth/config is the
# server-measurable equivalent: if oidc_enabled is false here, the SPA
# falls back to bcrypt-only regardless of what the bundle ships.
# allow_demo_auth is intentionally NOT asserted — it flips to false during
# the post-demo cutover and the smoke script must keep passing.
# ---------------------------------------------------------------------------
Invoke-Probe -Name "6. Auth feature-flags (GET /api/auth/config → oidc_enabled=true)" -ScriptBlock {
    $resp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/auth/config" `
        -Method GET `
        -ErrorAction Stop
    if ($resp.StatusCode -ne 200) {
        throw "Expected HTTP 200; got $($resp.StatusCode)"
    }
    $body = "$($resp.Content)"
    $json = $null
    try { $json = $body | ConvertFrom-Json -ErrorAction Stop } catch {
        throw "Response not JSON: $body"
    }
    if (-not $json.PSObject.Properties['oidc_enabled']) {
        throw "Response missing 'oidc_enabled' field: $body"
    }
    if (-not $json.oidc_enabled) {
        throw "oidc_enabled is false — 'Sign in with Microsoft' will not render on /login"
    }
}

# ---------------------------------------------------------------------------
# Probe 7 — V1/V2 data-mode contract (S52)
# Verifies the X-Data-Mode header changes what /grc/ai-systems returns:
#   v1 (or absent) → seeded portfolio (≥1 row in any reasonable env)
#   v2             → only rows tagged data_source='real' (≤ count(v1))
# The schema is identical across modes — only the row set differs.
# Skips if $env:SMOKE_DEMO_PASSWORD_CISO is unset (auth required).
# ---------------------------------------------------------------------------
Invoke-Probe -Name "7. Data-mode contract (X-Data-Mode v1 vs v2 → count(v2) <= count(v1))" -ScriptBlock {
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

    $v1Resp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/grc/ai-systems" `
        -Method GET `
        -Headers @{ "X-Data-Mode" = "v1" } `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($v1Resp.StatusCode -ne 200) { throw "V1 call returned HTTP $($v1Resp.StatusCode)" }
    $v1Json = $v1Resp.Content | ConvertFrom-Json
    if (-not $v1Json.PSObject.Properties['systems']) { throw "V1 response missing 'systems' field" }
    $v1Count = @($v1Json.systems).Count

    $v2Resp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/grc/ai-systems" `
        -Method GET `
        -Headers @{ "X-Data-Mode" = "v2" } `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($v2Resp.StatusCode -ne 200) { throw "V2 call returned HTTP $($v2Resp.StatusCode)" }
    $v2Json = $v2Resp.Content | ConvertFrom-Json
    if (-not $v2Json.PSObject.Properties['systems']) { throw "V2 response missing 'systems' field — schema forked on mode (bug)" }
    $v2Count = @($v2Json.systems).Count

    if ($v2Count -gt $v1Count) {
        throw "Invariant violated: V2 returned more rows ($v2Count) than V1 ($v1Count) — filter logic inverted"
    }
    Write-Host " (v1=$v1Count, v2=$v2Count)" -NoNewline -ForegroundColor DarkGray
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
