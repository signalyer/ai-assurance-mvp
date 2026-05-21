$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw ".env not found at $envFile" }

$allow = @("ANTHROPIC_API_KEY","OPENAI_API_KEY","LANGFUSE_PUBLIC_KEY","LANGFUSE_SECRET_KEY","LANGFUSE_HOST")
$pairs = @()
$pushed = @()

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $idx = $line.IndexOf("=")
    if ($idx -lt 1) { return }
    $key = $line.Substring(0, $idx).Trim()
    $val = $line.Substring($idx + 1).Trim()
    if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Substring(1, $val.Length - 2) }
    if ($allow -contains $key -and $val.Length -gt 0) {
        $pairs += ("{0}={1}" -f $key, $val)
        $pushed += $key
    }
}

if ($pairs.Count -eq 0) {
    Write-Host "No allow-listed secrets in .env."
    exit 0
}

Write-Host ("Pushing " + $pushed.Count + " settings: " + ($pushed -join ", "))
az webapp config appsettings set --name app-aigovern-dev --resource-group rg-aigovern-dev --settings $pairs -o none
Write-Host "Done."
