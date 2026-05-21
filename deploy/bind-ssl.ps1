$ErrorActionPreference = "Continue"
$FQDN = "aigovern.sandboxhub.co"
$APP  = "app-aigovern-dev"
$RG   = "rg-aigovern-dev"

Write-Host "Waiting for managed cert..."
$tp = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 10
    $tp = az webapp config ssl list --resource-group $RG --query "[?subjectName=='$FQDN'].thumbprint | [0]" -o tsv 2>$null
    if ($tp) {
        Write-Host ("[" + $i + "] thumbprint=" + $tp)
        break
    }
    Write-Host ("[" + $i + "] not yet issued")
}
if (-not $tp) { Write-Host "TIMEOUT waiting for cert"; exit 1 }

Write-Host "Binding SSL (SNI)..."
az webapp config ssl bind --certificate-thumbprint $tp --ssl-type SNI --name $APP --resource-group $RG -o none 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "bind failed"; exit 1 }

Write-Host "Probing https://$FQDN/api/health..."
for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 10
    $code = curl.exe -s -o NUL -w "%{http_code}" "https://$FQDN/api/health"
    Write-Host ("[" + $i + "] -> " + $code)
    if ($code -eq "200") { exit 0 }
}
exit 1
