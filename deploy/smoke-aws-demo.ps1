Add-Type -AssemblyName System.Web
$base = "https://aigovern.sandboxhub.co"

$line = (Select-String -Path "$PSScriptRoot\creds.txt" -Pattern "^demo-ciso\s" | Select-Object -First 1).Line
$p = ($line -split "\s+", 2)[1].Trim()
$body = "username=demo-ciso&password=" + [System.Web.HttpUtility]::UrlEncode($p) + "&next=/"
$jar = "$PSScriptRoot\jar.txt"
if (Test-Path $jar) { Remove-Item $jar }
$lc = curl.exe -s -c $jar --max-time 15 -o NUL -w "%{http_code}" -X POST -H "Content-Type: application/x-www-form-urlencoded" --data $body "$base/api/auth/login"
Write-Host ("login -> " + $lc)

$paths = @(
    "/demo-aws-analyzer",
    "/api/aws-demo",
    "/api/aws-demo/document",
    "/api/aws-demo/step/intake",
    "/api/aws-demo/step/risk_classification",
    "/api/aws-demo/step/required_controls",
    "/api/aws-demo/step/release_gates",
    "/api/ai-systems/ai-sys-001/edit-info"
)
foreach ($pt in $paths) {
    $c = curl.exe -s -b $jar --max-time 15 -o NUL -w "%{http_code}" "$base$pt"
    Write-Host ("  " + $c + "  " + $pt)
}
Remove-Item $jar -ErrorAction SilentlyContinue
