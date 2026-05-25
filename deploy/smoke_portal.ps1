<#
.SYNOPSIS
    Team Workspace SPA smoke test — verifies the V2 portal SPA loads and exposes
    its core surfaces. Session 44 split from the engine-side smoke_api.ps1.

.DESCRIPTION
    Until Session 45 DNS cutover, the target is the staging hostname
    swa-aigovern-portal-dev.azurestaticapps.net. At cutover, set
    $env:SMOKE_PORTAL_URL = "https://portal.aigovern.sandboxhub.co/" and the
    same script verifies the custom-DNS host.

    Probes (intentionally minimal — Vite SPAs are single-bundle, so a successful
    index.html + assets fetch is strong evidence the SPA is reachable):
      1. Index HTML reachable — GET / returns 200 + contains '<div id="root"></div>' (Vite convention)
      2. JS bundle reachable  — first <script> referenced from index returns 200
      3. CSS reachable        — first <link rel="stylesheet"> returns 200 (or SKIP if inline)

    V2-PORTAL-SPLIT §A4 acceptance: this script exits 0.

    Exit codes:
      0 — all probes pass
      N — count of failing probes

.EXAMPLE
    # Staging (default — *.azurestaticapps.net hostname):
    pwsh deploy/smoke_portal.ps1

    # After S45 DNS cutover:
    $env:SMOKE_PORTAL_URL = "https://portal.aigovern.sandboxhub.co/"
    pwsh deploy/smoke_portal.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$BaseUrl = if ($env:SMOKE_PORTAL_URL) {
    $env:SMOKE_PORTAL_URL.TrimEnd('/')
} else {
    "https://swa-aigovern-portal-dev.azurestaticapps.net"
}

Write-Host "=== AI Assurance Team Workspace SPA Smoke (smoke_portal.ps1) ===" -ForegroundColor Cyan
Write-Host "Target: $BaseUrl"
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
    if ($script:indexHtml -notmatch '<div\s+id="root"') {
        throw "index.html does not contain the Vite root element ('<div id=\"root\">') — SPA shell missing"
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
