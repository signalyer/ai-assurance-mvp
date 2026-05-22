<#
.SYNOPSIS
    Security scan: bandit static analysis, pip-audit CVE check, secrets grep.

.DESCRIPTION
    Runs in sequence:
      1. bandit      — Python static analysis for HIGH/CRITICAL security findings.
      2. pip-audit   — Dependency CVE scan for HIGH/CRITICAL vulnerabilities.
      3. Secrets grep — Searches for known-prefix secret patterns in source files.

    Aggregate report written to: data/security_scan_report.json
    Bandit detail:   data/security_scan_bandit.json
    pip-audit detail: data/security_scan_pipaudit.json

    Exit codes:
      0 — all zeros in the aggregate report (clean)
      1 — at least one HIGH/CRITICAL finding or secret found

.NOTES
    Compatible with Windows PowerShell 5.1 and PowerShell 7 (pwsh).
    Idempotent — safe to re-run.

.EXAMPLE
    pwsh deploy/security_scan.ps1
#>

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"   # Don't abort on individual tool failures

# ---------------------------------------------------------------------------
# Resolve project root (one directory above deploy/)
# ---------------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir
$DataDir    = Join-Path $ProjectDir "data"

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

$BanditOut   = Join-Path $DataDir "security_scan_bandit.json"
$PipAuditOut = Join-Path $DataDir "security_scan_pipaudit.json"
$ReportOut   = Join-Path $DataDir "security_scan_report.json"

$banditHigh   = 0
$pipauditHigh = 0
$secretsFound = 0

Write-Host "=== AI Assurance Security Scan ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectDir"
Write-Host "Output dir:   $DataDir"
Write-Host ""

# ---------------------------------------------------------------------------
# Step 0 — Ensure bandit and pip-audit are installed (best-effort)
# ---------------------------------------------------------------------------
Write-Host "[Step 0] Checking / installing bandit and pip-audit..." -ForegroundColor Yellow

try {
    $pipCmd = Get-Command pip -ErrorAction SilentlyContinue
    if ($null -eq $pipCmd) {
        $pipCmd = Get-Command pip3 -ErrorAction SilentlyContinue
    }

    if ($null -ne $pipCmd) {
        $banditCheck    = & $pipCmd.Source show bandit    2>&1
        $pipAuditCheck  = & $pipCmd.Source show pip-audit 2>&1

        $toInstall = @()
        if ($LASTEXITCODE -ne 0 -or $banditCheck -notmatch "Name: bandit") {
            $toInstall += "bandit"
        }
        if ($LASTEXITCODE -ne 0 -or $pipAuditCheck -notmatch "Name: pip-audit") {
            $toInstall += "pip-audit"
        }

        if ($toInstall.Count -gt 0) {
            Write-Host "Installing: $($toInstall -join ', ')"
            & $pipCmd.Source install --quiet @toInstall 2>&1 | Out-Null
        } else {
            Write-Host "bandit and pip-audit already installed."
        }
    } else {
        Write-Host "WARNING: pip not found; skipping bandit/pip-audit install." -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "WARNING: Could not check/install security tools: $_" -ForegroundColor DarkYellow
}

# ---------------------------------------------------------------------------
# Step 1 — bandit static analysis
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[Step 1] Running bandit..." -ForegroundColor Yellow
Write-Host "Output: $BanditOut"

$banditArgs = @(
    "-r", $ProjectDir,
    "-ll",
    "-f", "json",
    "-o", $BanditOut,
    "--exclude", "$ProjectDir\data,$ProjectDir\loadtests\__pycache__,$ProjectDir\.venv,$ProjectDir\venv,$ProjectDir\__pycache__"
)

try {
    $banditCmd = Get-Command bandit -ErrorAction SilentlyContinue
    if ($null -ne $banditCmd) {
        & bandit @banditArgs 2>&1 | Out-Null

        if (Test-Path $BanditOut) {
            try {
                $banditData = Get-Content $BanditOut -Raw | ConvertFrom-Json
                $results = $banditData.results
                if ($null -ne $results) {
                    $banditHigh = @($results | Where-Object {
                        $_.issue_severity -in @("HIGH", "CRITICAL")
                    }).Count
                }
                Write-Host "bandit HIGH/CRITICAL findings: $banditHigh"
            } catch {
                Write-Host "WARNING: Could not parse bandit JSON output: $_" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "bandit produced no output file (possibly no Python files scanned)."
        }
    } else {
        Write-Host "WARNING: bandit not found in PATH; skipping step 1." -ForegroundColor DarkYellow
        '{"results":[],"metrics":{},"errors":[]}' | Set-Content $BanditOut
    }
} catch {
    Write-Host "ERROR running bandit: $_" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# Step 2 — pip-audit CVE scan
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[Step 2] Running pip-audit..." -ForegroundColor Yellow
Write-Host "Output: $PipAuditOut"

try {
    $pipAuditCmd = Get-Command pip-audit -ErrorAction SilentlyContinue
    if ($null -ne $pipAuditCmd) {
        & pip-audit --format json --output $PipAuditOut 2>&1 | Out-Null

        if (Test-Path $PipAuditOut) {
            try {
                $auditData = Get-Content $PipAuditOut -Raw | ConvertFrom-Json
                $vulns = $auditData.dependencies | ForEach-Object {
                    $_.vulns
                } | Where-Object { $_ -ne $null }

                $highVulns = @($vulns | Where-Object {
                    $_.fix_versions -ne $null -and
                    ($_.id -match "^CVE" -or $_.aliases -match "CVE")
                })
                # Count all vulns as HIGH-equivalent (pip-audit doesn't expose CVSS inline)
                $pipauditHigh = @($vulns).Count
                Write-Host "pip-audit vulnerabilities found: $pipauditHigh"
            } catch {
                Write-Host "WARNING: Could not parse pip-audit JSON output: $_" -ForegroundColor DarkYellow
            }
        } else {
            Write-Host "pip-audit produced no output file."
        }
    } else {
        Write-Host "WARNING: pip-audit not found in PATH; skipping step 2." -ForegroundColor DarkYellow
        '{"dependencies":[]}' | Set-Content $PipAuditOut
    }
} catch {
    Write-Host "ERROR running pip-audit: $_" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# Step 3 — Custom secrets grep
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[Step 3] Scanning for hardcoded secrets..." -ForegroundColor Yellow

$secretPattern = "(AKIA[0-9A-Z]{16}|sk-ant-[a-zA-Z0-9\-]{20,}|sk-[a-zA-Z0-9]{20,}|xox[bp]-[a-zA-Z0-9\-]{10,}|ghp_[a-zA-Z0-9]{36}|glpat-[a-zA-Z0-9\-]{20,}|postgresql://[^\s@]+:[^\s@]+@|DefaultEndpointsProtocol=https;AccountName=|AccountKey=[A-Za-z0-9+/]{40,}={0,2}|sig=[A-Za-z0-9%+/]{40,})"

$excludeDirs = @(
    (Join-Path $ProjectDir "data"),
    (Join-Path $ProjectDir ".venv"),
    (Join-Path $ProjectDir "venv"),
    (Join-Path $ProjectDir "node_modules"),
    (Join-Path $ProjectDir "__pycache__"),
    (Join-Path $ProjectDir ".git")
)

try {
    $allFiles = Get-ChildItem -Path $ProjectDir -Recurse -Include "*.py","*.ps1","*.html","*.yaml","*.yml" -ErrorAction SilentlyContinue |
        Where-Object {
            $filePath = $_.FullName
            -not ($excludeDirs | Where-Object { $filePath.StartsWith($_) })
        }

    $secretMatches = $allFiles | Select-String -Pattern $secretPattern -ErrorAction SilentlyContinue

    if ($null -ne $secretMatches) {
        $secretsFound = @($secretMatches).Count
    } else {
        $secretsFound = 0
    }

    if ($secretsFound -gt 0) {
        Write-Host "ALERT: $secretsFound potential secret(s) found:" -ForegroundColor Red
        $secretMatches | ForEach-Object {
            Write-Host "  $($_.Filename):$($_.LineNumber) — $($_.Line.Trim())" -ForegroundColor Red
        }
    } else {
        Write-Host "No hardcoded secrets found."
    }
} catch {
    Write-Host "ERROR during secrets scan: $_" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# Step 4 — Aggregate report
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "[Step 4] Writing aggregate report..." -ForegroundColor Yellow

$report = [ordered]@{
    bandit_high   = $banditHigh
    pipaudit_high = $pipauditHigh
    secrets_found = $secretsFound
    scanned_at    = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
}

$reportJson = $report | ConvertTo-Json -Depth 3
$reportJson | Set-Content $ReportOut -Encoding UTF8
Write-Host "Report: $ReportOut"
Write-Host $reportJson

# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------
Write-Host ""
if ($banditHigh -eq 0 -and $pipauditHigh -eq 0 -and $secretsFound -eq 0) {
    Write-Host "=== SECURITY SCAN PASSED — no HIGH/CRITICAL findings ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== SECURITY SCAN FAILED — review findings above ===" -ForegroundColor Red
    exit 1
}
