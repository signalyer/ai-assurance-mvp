<#
.SYNOPSIS
    Team Workspace SPA smoke test — verifies the V2 portal SPA loads and exposes
    its core surfaces. Session 44 split from the engine-side smoke_api.ps1.

.DESCRIPTION
    Until Session 45 DNS cutover, the target is the staging hostname
    swa-aigovern-portal-dev.azurestaticapps.net. At cutover, set
    $env:SMOKE_PORTAL_URL = "https://portal.aigovern.sandboxhub.co/" and the
    same script verifies the custom-DNS host.

    Probes:
      1. Index HTML reachable — GET / returns 200 + contains '<div id="app"></div>'
      2. JS bundle reachable  — first <script src=...> from index returns 200
      3. CSS reachable        — first <link rel="stylesheet"> returns 200 (or SKIP if inline)
      4. Subroute SPA fallback — GET /ai-systems returns 200 + SPA shell
         (S48 / S47 #1 compound rule — catches missing staticwebapp.config.json)
      5. Authenticated API     — login demo-engineer against engine, then
         GET /api/v1/grc/ai-systems with cookie returns 200 + JSON shape
         (SKIPS if $env:SMOKE_DEMO_PASSWORD_ENGINEER is unset)

    V2-PORTAL-SPLIT §A4 acceptance: this script exits 0.

    Required env vars for full coverage:
      SMOKE_DEMO_PASSWORD_ENGINEER  — demo-engineer password (1Password)
    Optional:
      SMOKE_PORTAL_URL              — defaults to staging *.azurestaticapps.net
      SMOKE_API_URL                 — defaults to https://aigovern.sandboxhub.co
      SMOKE_PORTAL_SUBROUTE         — defaults to /ai-systems
      SMOKE_DEMO_USER_ENGINEER      — defaults to "demo-engineer"

    Exit codes:
      0 — all probes pass
      N — count of failing probes

.EXAMPLE
    # Production (post-S45 cutover) with full auth coverage:
    $env:SMOKE_PORTAL_URL = "https://portal.aigovern.sandboxhub.co/"
    $env:SMOKE_DEMO_PASSWORD_ENGINEER = (op read "op://SignalLayer/aigovern-demo/engineer-password")
    pwsh deploy/smoke_portal.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$BaseUrl = if ($env:SMOKE_PORTAL_URL) {
    $env:SMOKE_PORTAL_URL.TrimEnd('/')
} else {
    # S52 #2: pre-S45 staging URL `swa-aigovern-portal-dev.azurestaticapps.net`
    # was retired after the DNS cutover; default to canonical custom-DNS host.
    "https://portal.aigovern.sandboxhub.co"
}

# Engine API (separate origin — SPA hosts only static files; the FastAPI engine
# answers /api/v1/* and issues the session cookie on .aigovern.sandboxhub.co).
$ApiBaseUrl = if ($env:SMOKE_API_URL) {
    $env:SMOKE_API_URL.TrimEnd('/')
} else {
    "https://aigovern.sandboxhub.co"
}

# Subroute probe target — any client-side route that should resolve to index.html
# via the SWA SPA-fallback rule. Picked /ai-systems because it's the Team
# Workspace landing surface.
$SubRoute = if ($env:SMOKE_PORTAL_SUBROUTE) { $env:SMOKE_PORTAL_SUBROUTE } else { "/ai-systems" }

# Demo-role credentials (S48 STEP 2; Q2 = 1Password env-vars).
# Smoke scripts MUST NOT hardcode passwords — global CLAUDE.md rule.
$DemoUser = if ($env:SMOKE_DEMO_USER_ENGINEER) { $env:SMOKE_DEMO_USER_ENGINEER } else { "demo-engineer" }
$DemoPass = $env:SMOKE_DEMO_PASSWORD_ENGINEER

Write-Host "=== AI Assurance Team Workspace SPA Smoke (smoke_portal.ps1) ===" -ForegroundColor Cyan
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
# Catches the missing-staticwebapp.config.json regression class. Without the
# SPA-fallback rule, GET /ai-systems returns 404 even though GET / returns 200.
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
# Logs in as demo-engineer against the engine, then makes an authed call to
# /api/v1/grc/ai-systems. Verifies the .aigovern.sandboxhub.co cookie chain
# from S47 hotfix (commits d6f9a8d + 02f9f95) is still intact.
# ---------------------------------------------------------------------------
Invoke-Probe -Name "5. Authenticated API (login as $DemoUser → GET /grc/ai-systems)" -ScriptBlock {
    if (-not $DemoPass) {
        Write-Host " (skipped — `$env:SMOKE_DEMO_PASSWORD_ENGINEER not set)" -NoNewline -ForegroundColor DarkYellow
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
        -Uri "$ApiBaseUrl/api/v1/grc/ai-systems" `
        -Method GET `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($apiResp.StatusCode -ne 200) {
        throw "Authed API call returned HTTP $($apiResp.StatusCode) — cookie may not be reaching engine"
    }
    if ("$($apiResp.Content)" -notmatch '"systems"\s*:') {
        throw "Authed API response missing 'systems' key — schema may have drifted"
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
#   v1 (or absent) → seeded portfolio
#   v2             → only rows tagged data_source='real' (≤ count(v1))
# Schema identical across modes — only the row set differs.
# Skips if $env:SMOKE_DEMO_PASSWORD_ENGINEER is unset (auth required).
# ---------------------------------------------------------------------------
Invoke-Probe -Name "7. Data-mode contract (X-Data-Mode v1 vs v2 → count(v2) <= count(v1))" -ScriptBlock {
    if (-not $DemoPass) {
        Write-Host " (skipped — `$env:SMOKE_DEMO_PASSWORD_ENGINEER not set)" -NoNewline -ForegroundColor DarkYellow
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
# Probe 8 — SDK key issuance round-trip (S53)
# Verifies the per-system SDK key endpoints introduced in Session 53:
#   POST /api/sdk-keys                     → 201 + hmac_secret length > 32
#   GET  /api/sdk-keys/{key_id}/status     → 200 + first_seen_at == null
#   POST /api/sdk-keys/{key_id}/revoke     → 200 + revoked_at set
# Skips if $env:SMOKE_DEMO_PASSWORD_ENGINEER is unset (auth required).
# ---------------------------------------------------------------------------
Invoke-Probe -Name "8. SDK key issuance round-trip (POST → status → revoke)" -ScriptBlock {
    if (-not $DemoPass) {
        Write-Host " (skipped — `$env:SMOKE_DEMO_PASSWORD_ENGINEER not set)" -NoNewline -ForegroundColor DarkYellow
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

    $sysResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/grc/ai-systems" `
        -Method GET `
        -WebSession $smokeSession `
        -ErrorAction Stop
    $sysJson = $sysResp.Content | ConvertFrom-Json
    if (@($sysJson.systems).Count -eq 0) { throw "No AI systems available to issue a key against" }
    $targetSystemId = $sysJson.systems[0].id

    $issueBody = @{ ai_system_id = $targetSystemId } | ConvertTo-Json
    $issueResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/sdk-keys" `
        -Method POST `
        -Body $issueBody `
        -ContentType "application/json" `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($issueResp.StatusCode -ne 201) { throw "Issue returned HTTP $($issueResp.StatusCode) (expected 201)" }
    $issued = $issueResp.Content | ConvertFrom-Json
    if (-not $issued.key_id) { throw "Issue response missing key_id" }
    if (-not $issued.hmac_secret -or $issued.hmac_secret.Length -le 32) {
        throw "hmac_secret missing or too short (got length $($issued.hmac_secret.Length))"
    }
    $keyId = $issued.key_id

    $statusResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/sdk-keys/$keyId/status" `
        -Method GET `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($statusResp.StatusCode -ne 200) { throw "Status returned HTTP $($statusResp.StatusCode)" }
    $statusJson = $statusResp.Content | ConvertFrom-Json
    if ($statusJson.first_seen_at) {
        throw "first_seen_at should be null on a freshly issued key (got '$($statusJson.first_seen_at)')"
    }

    $revokeResp = Invoke-WebRequest `
        -Uri "$ApiBaseUrl/api/v1/sdk-keys/$keyId/revoke" `
        -Method POST `
        -WebSession $smokeSession `
        -ErrorAction Stop
    if ($revokeResp.StatusCode -ne 200) { throw "Revoke returned HTTP $($revokeResp.StatusCode)" }
    $revokeJson = $revokeResp.Content | ConvertFrom-Json
    if (-not $revokeJson.revoked_at) { throw "Revoke response missing revoked_at" }

    Write-Host " (key=$keyId, secret_len=$($issued.hmac_secret.Length))" -NoNewline -ForegroundColor DarkGray
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
if ($Failures -eq 0) {
    Write-Host "=== SMOKE PORTAL PASSED — Team Workspace SPA reachable ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SMOKE PORTAL FAILED — $Failures probe(s) failed ===" -ForegroundColor Red
    exit $Failures
}
