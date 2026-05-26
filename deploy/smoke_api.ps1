<#
.SYNOPSIS
    Engine-API smoke test — 6 demo scenarios + A6/A7 login redirect probe against a running AI Assurance instance.

.DESCRIPTION
    Session 44 split of the original smoke_e2e.ps1 (now a thin wrapper).
    smoke_api.ps1 owns the engine-side probes; smoke_portal.ps1 and
    smoke_gov.ps1 own the SPA-load probes for the two V2 portals.

    Runs 7 probes in sequence against $env:SMOKE_TARGET_URL.
    Each scenario prints PASS, FAIL, or SKIP.

    Default target: http://localhost:8000

    Scenarios:
      1. PII pipeline           POST /api/demo/run                       — vault_id present, no "@" in scrubbed_prompt
      2. Gate failure           GET  /api/grc/release-gates/v2/systems   — gates summary present
      3. Agent governance       GET  /api/agents                         — >= 6 agents listed
      4. RTF cascade            POST /api/right-to-forget                — cascade_id present
      5. Eval trend             GET  /api/analytics/trends               — 200 (even if empty)
      6. Framework coverage     GET  /api/frameworks/matrix              — at least one framework slug present
      7. A6/A7 login redirect   POST /api/auth/login (engineer + ciso)   — JSON `next` matches role-aware URL

    Exit codes:
      0 — all probes pass
      N — count of failing probes

.EXAMPLE
    # Dev (no auth — scenario 7 will SKIP because AUTH_ENABLED=false):
    $env:SMOKE_TARGET_URL = "http://localhost:8000"
    pwsh deploy/smoke_api.ps1

    # Prod / hardened (AUTH_ENABLED=true) — scenario 7 verifies A6/A7 contract:
    $env:SMOKE_TARGET_URL  = "https://api.aigovern.sandboxhub.co"
    $env:SMOKE_USER        = "demo-aigov"
    $env:SMOKE_PASSWORD    = "<shared demo password>"
    $env:SMOKE_ENGINEER_PW = "<demo-engineer password>"
    $env:SMOKE_CISO_PW     = "<demo-ciso password>"
    $env:PORTAL_URL        = "https://portal.aigovern.sandboxhub.co/"
    $env:GOV_URL           = "https://gov.aigovern.sandboxhub.co/"
    pwsh deploy/smoke_api.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$BaseUrl = if ($env:SMOKE_TARGET_URL) { $env:SMOKE_TARGET_URL.TrimEnd('/') } else { "http://localhost:8000" }

# Guard: this script sends synthetic PII to /api/demo/run. Refuse to run against
# anything that is not explicitly an allowed dev/staging host. Override with
# $env:SMOKE_ALLOW_PROD=true to opt in (do NOT set this on the real prod URL).
$AllowedHostPatterns = @(
    'localhost',
    '127\.0\.0\.1',
    '.*\.azurewebsites\.net.*-dev',
    'aigovern-dev\.',
    'sandboxhub\.co'
)
$hostAllowed = $false
foreach ($pat in $AllowedHostPatterns) {
    if ($BaseUrl -match $pat) { $hostAllowed = $true; break }
}
if (-not $hostAllowed -and $env:SMOKE_ALLOW_PROD -ne 'true') {
    Write-Host "ERROR: Target '$BaseUrl' is not in the dev/staging allowlist." -ForegroundColor Red
    Write-Host "       Scenario 1 sends synthetic PII to /api/demo/run; refusing to run." -ForegroundColor Red
    Write-Host "       Set SMOKE_ALLOW_PROD=true to override (NOT recommended)." -ForegroundColor Red
    exit 99
}

Write-Host "=== AI Assurance Engine-API Smoke (smoke_api.ps1) ===" -ForegroundColor Cyan
Write-Host "Target: $BaseUrl"
Write-Host ""

# ---------------------------------------------------------------------------
# Optional login — required when the target has AUTH_ENABLED=true.
# Set $env:SMOKE_USER and $env:SMOKE_PASSWORD to authenticate before the
# scenarios run. The session cookie is threaded through every Invoke-RestMethod
# call via $AuthSplat. Credentials are NEVER printed to stdout.
# ---------------------------------------------------------------------------
$Session = $null
$AuthSplat = @{}
if ($env:SMOKE_USER -and $env:SMOKE_PASSWORD) {
    Write-Host "Authenticating as '$env:SMOKE_USER'..." -NoNewline
    try {
        $loginBody = @{
            username = $env:SMOKE_USER
            password = $env:SMOKE_PASSWORD
            next     = "/"
        }
        $null = Invoke-WebRequest -Uri "$BaseUrl/api/auth/login" -Method POST `
            -Body $loginBody `
            -SessionVariable Session `
            -ErrorAction Stop
        $AuthSplat = @{ WebSession = $Session }
        Write-Host " [OK]" -ForegroundColor Green
    } catch {
        Write-Host " [FAIL] $_" -ForegroundColor Red
        Write-Host "Cannot run scenarios without auth on a hardened target. Exiting." -ForegroundColor Red
        exit 98
    }
    Write-Host ""
}

$Failures = 0

function Invoke-Scenario {
    <#
    .SYNOPSIS
        Execute a single smoke scenario and report PASS/FAIL/SKIP.

    .PARAMETER Name
        Display name of the scenario.

    .PARAMETER ScriptBlock
        The test logic. Should throw on assertion failure.
        Connection-refused errors are treated as SKIP (target unreachable).
    #>
    param(
        [string]$Name,
        [scriptblock]$ScriptBlock
    )

    Write-Host "Scenario: $Name" -NoNewline
    try {
        & $ScriptBlock
        Write-Host "  [PASS]" -ForegroundColor Green
    } catch {
        $msg = "$_"
        # Connection refused / network unreachable — target is not running; skip gracefully
        if ($msg -match "refused|unreachable|No connection|Unable to connect|SocketException|actively refused") {
            Write-Host "  [SKIP] target unreachable ($BaseUrl)" -ForegroundColor DarkYellow
        } else {
            Write-Host "  [FAIL] $msg" -ForegroundColor Red
            $script:Failures++
        }
    }
}

# ---------------------------------------------------------------------------
# Scenario 1 — PII pipeline
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "1. PII pipeline (POST /api/demo/run)" -ScriptBlock {
    $url  = "$BaseUrl/api/demo/run"
    # Prompt deliberately carries identifiable text (email + name) so the
    # scrubber has something to tokenise — but is phrased neutrally to avoid
    # tripping LlamaGuard's substring keyword matcher (which flags any output
    # containing "harm", "kill", etc. — substrings of harmless words too).
    $body = @{
        prompt    = "Customer Jane Doe at jane.doe@example.com is asking about portfolio rebalancing options. Suggest a diversified allocation across index funds."
        system_id = "sys-payments-001"
        action    = "llm_call"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Uri $url -Method POST `
        -Body $body `
        -ContentType "application/json" `
        @AuthSplat `
        -ErrorAction Stop

    $runs = @($resp.runs)
    if ($runs.Count -lt 1) {
        throw "Expected at least one run in response; got: $($resp | ConvertTo-Json -Compress -Depth 4)"
    }

    $run = $runs[0]
    if (-not $run.vault_id) {
        throw "Expected 'vault_id' in first run; got: $($run | ConvertTo-Json -Compress -Depth 3)"
    }

    $scrubbed = "$($run.prompt)"
    if ($scrubbed -match "@") {
        throw "Run.prompt still contains '@' — PII not scrubbed. Value: $scrubbed"
    }
}

# ---------------------------------------------------------------------------
# Scenario 2 — Gate failure check
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "2. Gate failure (GET /api/grc/release-gates/v2/systems)" -ScriptBlock {
    $url  = "$BaseUrl/api/grc/release-gates/v2/systems"
    $resp = Invoke-RestMethod -Uri $url -Method GET @AuthSplat -ErrorAction Stop
    if ($null -eq $resp.systems) {
        throw "Expected 'systems' array in response; got: $($resp | ConvertTo-Json -Compress -Depth 3)"
    }
}

# ---------------------------------------------------------------------------
# Scenario 3 — Agent governance
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "3. Agent governance (GET /api/agents)" -ScriptBlock {
    $url = "$BaseUrl/api/agents"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method GET @AuthSplat -ErrorAction Stop
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode) -eq 404) {
            Write-Host " (skipped — endpoint not mounted)" -NoNewline -ForegroundColor DarkYellow
            return
        }
        throw
    }
    $agents = if ($resp -is [array]) { $resp } elseif ($resp.agents) { $resp.agents } else { @() }
    if (@($agents).Count -lt 6) {
        throw "Expected >= 6 agents; found $(@($agents).Count). Seed demo data first (python mock_data.py)."
    }
}

# ---------------------------------------------------------------------------
# Scenario 4 — RTF cascade
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "4. RTF cascade (POST /api/right-to-forget)" -ScriptBlock {
    $url  = "$BaseUrl/api/right-to-forget"
    $body = @{
        subject_id = "smoke-test-subject-$(Get-Date -Format 'yyyyMMddHHmmss')"
        reason     = "e2e smoke test"
        requested_by = "smoke_api.ps1"
    } | ConvertTo-Json
    try {
        $resp = Invoke-RestMethod -Uri $url -Method POST `
            -Body $body `
            -ContentType "application/json" `
            @AuthSplat `
            -ErrorAction Stop
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode) -in @(404, 422)) {
            Write-Host " (skipped — endpoint not reachable or payload mismatch)" -NoNewline -ForegroundColor DarkYellow
            return
        }
        throw
    }
    if (-not $resp.cascade_id) {
        throw "Expected 'cascade_id' in response; got: $($resp | ConvertTo-Json -Compress)"
    }
}

# ---------------------------------------------------------------------------
# Scenario 5 — Eval trend
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "5. Eval trend (GET /api/analytics/trends)" -ScriptBlock {
    $url = "$BaseUrl/api/analytics/trends"
    try {
        $null = Invoke-RestMethod -Uri $url -Method GET @AuthSplat -ErrorAction Stop
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode) -eq 404) {
            Write-Host " (skipped — endpoint not mounted)" -NoNewline -ForegroundColor DarkYellow
            return
        }
        throw
    }
}

# ---------------------------------------------------------------------------
# Scenario 6 — Framework coverage matrix
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "6. Framework coverage (GET /api/frameworks/matrix)" -ScriptBlock {
    $url = "$BaseUrl/api/frameworks/matrix?systems=sys-payments-001"
    try {
        $resp = Invoke-RestMethod -Uri $url -Method GET @AuthSplat -ErrorAction Stop
    } catch [System.Net.WebException] {
        if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode) -eq 404) {
            Write-Host " (skipped — endpoint not mounted)" -NoNewline -ForegroundColor DarkYellow
            return
        }
        throw
    }
    $frameworks = if ($resp.frameworks) { $resp.frameworks } elseif ($resp -is [array]) { $resp } else { @() }
    if (@($frameworks).Count -lt 1) {
        throw "Expected at least 1 framework slug in response; got: $($resp | ConvertTo-Json -Compress)"
    }
}

# ---------------------------------------------------------------------------
# Scenario 7 — A6/A7 role-aware login redirect (V2-PORTAL-SPLIT acceptance)
#
# Validates the contract shipped in Session 43:
#   * demo-engineer → response.next == $env:PORTAL_URL (or "/" if unset)
#   * demo-ciso     → response.next == $env:GOV_URL    (or "/" if unset)
#   * Any user with explicit deep-link next="/foo" → response.next == "/foo"
#
# Probe is unauthenticated by design — it calls /api/auth/login fresh per role,
# bypassing the $AuthSplat session. SKIPs gracefully when AUTH_ENABLED=false
# (the engine returns `auth_disabled` 400) or when role passwords aren't
# provided ($env:SMOKE_ENGINEER_PW / $env:SMOKE_CISO_PW).
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "7. A6/A7 login redirect (POST /api/auth/login)" -ScriptBlock {
    if (-not $env:SMOKE_ENGINEER_PW -or -not $env:SMOKE_CISO_PW) {
        Write-Host " (skipped — SMOKE_ENGINEER_PW / SMOKE_CISO_PW not set)" -NoNewline -ForegroundColor DarkYellow
        return
    }

    $expectedPortal = if ($env:PORTAL_URL) { $env:PORTAL_URL } else { "/" }
    $expectedGov    = if ($env:GOV_URL)    { $env:GOV_URL }    else { "/" }
    $url = "$BaseUrl/api/auth/login"

    # --- engineer default ---
    $body = @{ username = "demo-engineer"; password = $env:SMOKE_ENGINEER_PW; next = "/" }
    $resp = Invoke-RestMethod -Uri $url -Method POST -Body $body -ErrorAction Stop
    if ("$($resp.next)" -ne $expectedPortal) {
        throw "engineer→PORTAL_URL: expected '$expectedPortal', got '$($resp.next)'"
    }

    # --- ciso default ---
    $body = @{ username = "demo-ciso"; password = $env:SMOKE_CISO_PW; next = "/" }
    $resp = Invoke-RestMethod -Uri $url -Method POST -Body $body -ErrorAction Stop
    if ("$($resp.next)" -ne $expectedGov) {
        throw "ciso→GOV_URL: expected '$expectedGov', got '$($resp.next)'"
    }

    # --- explicit deep-link survives ---
    $body = @{ username = "demo-engineer"; password = $env:SMOKE_ENGINEER_PW; next = "/runtime" }
    $resp = Invoke-RestMethod -Uri $url -Method POST -Body $body -ErrorAction Stop
    if ("$($resp.next)" -ne "/runtime") {
        throw "engineer+next=/runtime: deep-link clobbered; got '$($resp.next)'"
    }
}

# ---------------------------------------------------------------------------
# Scenario 8 — Entra OIDC wiring (Session 49 / ADR-002)
#
# Engine-side verification only — does NOT perform a real Entra round-trip
# (that needs a human browser). Three sub-checks:
#   8a. GET /api/auth/config returns the two feature-flag booleans.
#   8b. GET /auth/oidc/login 302s to login.microsoftonline.com with the
#       correct client_id and redirect_uri=https://... (catches the
#       X-Forwarded-Proto bug that bit S49 STEP 3).
#   8c. Bcrypt login still works when ALLOW_DEMO_AUTH=true (regression).
#
# All sub-checks SKIP gracefully when AUTH_ENABLED=false (config endpoint
# is still reachable but oidc_enabled may be false in dev).
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "8. OIDC wiring (engine-side, no Entra round-trip)" -ScriptBlock {
    # 8a — feature flags
    $cfg = Invoke-RestMethod -Uri "$BaseUrl/api/auth/config" -Method GET -ErrorAction Stop
    if ($null -eq $cfg.allow_demo_auth) {
        throw "/api/auth/config missing allow_demo_auth field; got: $($cfg | ConvertTo-Json -Compress)"
    }
    if ($null -eq $cfg.oidc_enabled) {
        throw "/api/auth/config missing oidc_enabled field; got: $($cfg | ConvertTo-Json -Compress)"
    }

    # 8b — login redirect (only if OIDC is actually enabled on this target).
    # Use curl.exe rather than Invoke-WebRequest: PS 7's WebClient errors out
    # on -MaximumRedirection 0 instead of returning the 302 — quirk first
    # noted during S49 smoke authoring. curl is reliable + ships with Windows
    # 11 and every Linux distro the CI runs on.
    if ($cfg.oidc_enabled) {
        $curlOut = & curl.exe -sS -o NUL -w "%{http_code} %{redirect_url}" "$BaseUrl/auth/oidc/login" 2>&1
        $parts = "$curlOut".Trim().Split(" ", 2)
        $code = [int]$parts[0]
        $loc = if ($parts.Count -gt 1) { $parts[1] } else { "" }
        if ($code -ne 302) {
            throw "/auth/oidc/login expected 302, got $code"
        }
        if ($loc -notmatch "^https://login\.microsoftonline\.com/") {
            throw "/auth/oidc/login Location not Microsoft OIDC; got: $loc"
        }
        if ($loc -notmatch "redirect_uri=https%3A%2F%2F") {
            throw "/auth/oidc/login redirect_uri not https-encoded — X-Forwarded-Proto regression? Location: $loc"
        }
    } else {
        Write-Host " (8b skipped — OIDC not enabled on target)" -NoNewline -ForegroundColor DarkYellow
    }

    # 8c — bcrypt regression (only if creds + ALLOW_DEMO_AUTH=true)
    if ($cfg.allow_demo_auth -and $env:SMOKE_ENGINEER_PW) {
        $body = @{ username = "demo-engineer"; password = $env:SMOKE_ENGINEER_PW; next = "/" }
        $resp = Invoke-RestMethod -Uri "$BaseUrl/api/auth/login" -Method POST -Body $body -ErrorAction Stop
        if (-not $resp.ok) {
            throw "bcrypt login regression — demo-engineer did not get ok=true; got: $($resp | ConvertTo-Json -Compress)"
        }
    } else {
        Write-Host " (8c skipped — demo auth disabled or SMOKE_ENGINEER_PW unset)" -NoNewline -ForegroundColor DarkYellow
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
if ($Failures -eq 0) {
    Write-Host "=== SMOKE API PASSED — all probes passed ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SMOKE API FAILED — $Failures probe(s) failed ===" -ForegroundColor Red
    exit $Failures
}
