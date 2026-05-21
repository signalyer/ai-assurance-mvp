$ErrorActionPreference = "Continue"
Write-Host "Uploading zip..."
$null = az webapp deployment source config-zip --name app-aigovern-dev --resource-group rg-aigovern-dev --src C:/ai-assurance-mvp/deploy/app.zip --timeout 1200 2>$null
Write-Host "Polling Kudu..."
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 10
    $s = az webapp log deployment list --name app-aigovern-dev --resource-group rg-aigovern-dev --query "[0].status" -o tsv 2>$null
    Write-Host ("[" + $i + "] status=" + $s)
    if ($s -eq "4") { Write-Host "Deploy succeeded."; break }
    if ($s -eq "3") { Write-Host "Deploy FAILED."; exit 1 }
}
Write-Host "Waiting for /api/health..."
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 10
    $code = curl.exe -s -o NUL -w "%{http_code}" "https://app-aigovern-dev.azurewebsites.net/api/health"
    Write-Host ("[" + $i + "] /api/health -> " + $code)
    if ($code -eq "200") { exit 0 }
}
exit 1
