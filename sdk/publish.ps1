# publish.ps1 — Build wheel and upload to Azure Artifacts feed via twine.
# Day 9: Publish step is gated off — wire-ready for Day 10 hardening.

#Requires -Version 7

[CmdletBinding()]
param(
    [string]$FeedUrl = $env:SL_ARTIFACTS_FEED_URL,
    [string]$FeedUser = $env:SL_ARTIFACTS_FEED_USER,
    [string]$FeedToken = $env:SL_ARTIFACTS_FEED_TOKEN
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "=== SignalLayer SDK — build + publish ==="
Write-Host "SDK version: $(python -c 'import tomllib; d=tomllib.load(open(\"pyproject.toml\",\"rb\")); print(d[\"project\"][\"version\"])')"
Write-Host ""

# Step 1: Clean previous dist
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
    Write-Host "Cleaned dist/"
}

# Step 2: Build wheel
Write-Host "Building wheel..."
python -m build --wheel --outdir dist .
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed — exit code $LASTEXITCODE"
    exit 1
}

$WheelFile = Get-ChildItem dist -Filter "*.whl" | Select-Object -First 1
if (-not $WheelFile) {
    Write-Error "No wheel found in dist/ after build"
    exit 1
}
Write-Host "Built: $($WheelFile.Name)"
Write-Host ""

# ============================================================
# DRY RUN — publish step gated off (Day 10 hardening)
# ============================================================
Write-Host "DRY RUN — publish step gated off (Day 10 hardening)"
Write-Host "Wheel is ready at: dist/$($WheelFile.Name)"
Write-Host "When unblocked, the upload command will be:"
Write-Host "  twine upload --repository-url `$FeedUrl -u `$FeedUser -p `$FeedToken dist/*.whl"
return

# --- Everything below is wired but NOT executed until Day 10 ---

# Validate feed credentials
if (-not $FeedUrl -or -not $FeedUser -or -not $FeedToken) {
    Write-Error "Missing Azure Artifacts feed credentials. Set SL_ARTIFACTS_FEED_URL, SL_ARTIFACTS_FEED_USER, SL_ARTIFACTS_FEED_TOKEN."
    exit 1
}

Write-Host "Uploading to Azure Artifacts: $FeedUrl"
twine upload --repository-url $FeedUrl -u $FeedUser -p $FeedToken dist/*.whl
if ($LASTEXITCODE -ne 0) {
    Write-Error "twine upload failed"
    exit 1
}
Write-Host "Published successfully."
