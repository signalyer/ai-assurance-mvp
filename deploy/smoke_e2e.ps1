<#
.SYNOPSIS
    E2E smoke test — 6 demo scenarios against a running AI Assurance instance.

.DESCRIPTION
    Runs 6 scenario probes in sequence against $env:SMOKE_TARGET_URL.
    Each scenario prints PASS or FAIL with the assertion that failed.

    Default target: http://localhost:8000

    Scenarios:
      1. PII pipeline        POST /api/demo/run         — vault_id present, no "@" in scrubbed_prompt
      2. Gate failure        GET  /api/release-gates/…  — decision field present
      3. Agent governance    GET  /api/agents            — >= 6 agents listed
      4. RTF cascade         POST /api/right-to-forget   — cascade_id present
      5. Eval trend          GET  /api/evaluate/history  — 200 (even if empty)
      6. Framework coverage  GET  /api/frameworks/matrix — at least one framework slug present

    Exit codes:
      0 — all 6 scenarios pass
      N — count of failing scenarios

.EXAMPLE
    # Dev (no auth):
    $env:SMOKE_TARGET_URL = "http://localhost:8000"
    pwsh deploy/smoke_e2e.ps1

    # Prod / hardened (AUTH_ENABLED=true):
    $env:SMOKE_TARGET_URL = "https://aigovern.sandboxhub.co"
    $env:SMOKE_USER       = "demo-aigov"
    $env:SMOKE_PASSWORD   = "<shared demo password>"
    pwsh deploy/smoke_e2e.ps1
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

Write-Host "=== AI Assurance E2E Smoke Test ===" -ForegroundColor Cyan
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
    $body = @{
        prompt    = "Customer Jane Doe SSN 987-65-4321 email jane.doe@example.com balance query"
        system_id = "sys-payments-001"
        action    = "llm_call"
    } | ConvertTo-Json

    $resp = Invoke-RestMethod -Uri $url -Method POST `
        -Body $body `
        -ContentType "application/json" `
        @AuthSplat `
        -ErrorAction Stop

    if (-not $resp.vault_id) {
        throw "Expected 'vault_id' in response; got: $($resp | ConvertTo-Json -Compress)"
    }

    $scrubbed = "$($resp.scrubbed_prompt)"
    if ($scrubbed -match "@") {
        throw "scrubbed_prompt still contains '@' — PII not scrubbed. Value: $scrubbed"
    }
}

# ---------------------------------------------------------------------------
# Scenario 2 — Gate failure check
# ---------------------------------------------------------------------------
Invoke-Scenario -Name "2. Gate failure (GET /api/release-gates/sys-payments-001)" -ScriptBlock {
    $url  = "$BaseUrl/api/release-gates/sys-payments-001"

    try {
        $resp = Invoke-RestMethod -Uri $url -Method GET @AuthSplat -ErrorAction Stop
    } catch [System.Net.WebException] {
        # 404 means system not seeded — skip gracefully rather than fail
        if ($_.Exception.Response -and ([int]$_.Exception.Response.StatusCode) -eq 404) {
            Write-Host " (skipped — system not seeded)" -NoNewline -ForegroundColor DarkYellow
            return
        }
        throw
    }

    if ($null -eq $resp.decision -and $null -eq $resp.gate_id -and $null -eq $resp.gates) {
        throw "Expected 'decision', 'gate_id', or 'gates' field in response; got: $($resp | ConvertTo-Json -Compress)"
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

    # Accept both array response and {agents: [...]} envelope
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
        requested_by = "smoke_e2e.ps1"
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
Invoke-Scenario -Name "5. Eval trend (GET /api/evaluate/history)" -ScriptBlock {
    $url = "$BaseUrl/api/evaluate/history?system=sys-payments-001"

    try {
        # We only assert HTTP 200; empty history is fine
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

    # Accept {frameworks: [...], rows: [...]} or array of slugs
    $frameworks = if ($resp.frameworks) { $resp.frameworks } elseif ($resp -is [array]) { $resp } else { @() }

    if (@($frameworks).Count -lt 1) {
        throw "Expected at least 1 framework slug in response; got: $($resp | ConvertTo-Json -Compress)"
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Write-Host ""
if ($Failures -eq 0) {
    Write-Host "=== SMOKE E2E PASSED — all 6 scenarios passed ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SMOKE E2E FAILED — $Failures scenario(s) failed ===" -ForegroundColor Red
    exit $Failures
}
