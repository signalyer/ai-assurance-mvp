# scripts/snapshot-azure.ps1
#
# Capture EVERYTHING needed to rebuild the rg-aigovern-dev stack from scratch.
# Writes to a timestamped folder under scripts/snapshots/. Run this BEFORE
# destroy-azure.ps1, or anytime as a routine backup.
#
# Captured:
#   * App Service: app settings (incl. secrets), site config, custom domain
#     bindings, slot settings, SKU
#   * App Service Plan: SKU, capacity
#   * Postgres flex: SKU, version, admin user, tier, storage, database list,
#     and a pg_dump of every database (requires `pg_dump` on PATH)
#   * AI Search: SKU, replicas, partitions, index definitions (REST API)
#   * Static Web Apps: name, SKU, custom domains, repo binding
#   * Key Vault: secret names + binary backup blobs (re-importable to any vault)
#   * App Insights: instrumentation key + connection string + workspace link
#   * Log Analytics: workspace ID + retention
#   * DNS zone: BIND-format export of every record set
#   * Alert rules: ARM templates (re-deployable)
#   * Action groups
#
# NOT captured (operator action required on rebuild):
#   * SSL certificates -- managed certs auto-reissue after DNS validates (~15 min)
#   * Application Insights *new* instrumentation key after recreate -- rebuild
#     script auto-updates App Service settings to the new key
#   * Static Web App build artifacts -- rebuild triggers `swa deploy` from
#     local source. Make sure team-portal/ and ciso-console/ are in correct state.
#
# SECURITY:
#   * The snapshot tarball CONTAINS SECRETS (app settings, Postgres password
#     if captured, KV secret backups). Treat it as sensitive material.
#   * gitignored via scripts/snapshots/ pattern.
#
# Usage:
#   .\scripts\snapshot-azure.ps1
#   .\scripts\snapshot-azure.ps1 -SkipPostgresDump   # if pg_dump unavailable
#   .\scripts\snapshot-azure.ps1 -OutputDir custom/path

param(
    [switch]$SkipPostgresDump,
    [string]$OutputDir = "",
    [string]$ResourceGroup = "rg-aigovern-dev",
    [string]$Subscription  = "SignalLayerDev"
)

$env:MSYS_NO_PATHCONV = "1"
$ProgressPreference   = "SilentlyContinue"

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
if (-not $OutputDir) {
    $OutputDir = Join-Path $PSScriptRoot "snapshots\$ts"
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$LogFile = Join-Path $OutputDir "snapshot.log"

function Log { param([string]$m); $l="[$(Get-Date -Format 'HH:mm:ss')] $m"; Write-Host $l; Add-Content $LogFile $l }

Log "=== snapshot-azure.ps1 starting ==="
Log "Output: $OutputDir"

az account set --subscription $Subscription 2>$null | Out-Null
$cur = (az account show --query "name" -o tsv 2>$null) -replace '\s',''
if ($cur -ne $Subscription) { Log "FATAL: sub mismatch ($cur)"; exit 1 }

$manifest = @{
    snapshot_timestamp = (Get-Date -Format "o")
    resource_group     = $ResourceGroup
    subscription       = $Subscription
    captured_by        = $env:USERNAME
    captured_files     = @()
}

# ---------------------------------------------------------------------------
# 1. Resource inventory (everything in the RG, by type)
# ---------------------------------------------------------------------------
Log "Capturing resource inventory..."
az resource list -g $ResourceGroup -o json 2>$null | Out-File "$OutputDir\resources.json" -Encoding UTF8
$manifest.captured_files += "resources.json"

# ---------------------------------------------------------------------------
# 2. App Service Plans
# ---------------------------------------------------------------------------
Log "Capturing App Service Plans..."
$plans = az appservice plan list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$plans | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\appservice-plans.json" -Encoding UTF8
$manifest.captured_files += "appservice-plans.json"

# ---------------------------------------------------------------------------
# 3. App Services + slots + settings + custom domains
# ---------------------------------------------------------------------------
Log "Capturing App Services..."
$webapps = az webapp list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$webappData = @()
foreach ($app in $webapps) {
    Log "  $($app.name)"
    $settings = az webapp config appsettings list -g $ResourceGroup -n $app.name -o json 2>$null | ConvertFrom-Json
    $config   = az webapp config show -g $ResourceGroup -n $app.name -o json 2>$null | ConvertFrom-Json
    $domains  = az webapp config hostname list -g $ResourceGroup --webapp-name $app.name -o json 2>$null | ConvertFrom-Json
    $slots    = az webapp deployment slot list -g $ResourceGroup --name $app.name -o json 2>$null | ConvertFrom-Json
    $slotData = @()
    foreach ($slot in $slots) {
        $slotSettings = az webapp config appsettings list -g $ResourceGroup -n $app.name --slot $slot.name -o json 2>$null | ConvertFrom-Json
        $slotData += @{
            name = $slot.name
            settings = $slotSettings
        }
    }
    $webappData += @{
        name           = $app.name
        location       = $app.location
        plan_id        = $app.appServicePlanId
        kind           = $app.kind
        runtime        = $config.linuxFxVersion
        settings       = $settings
        custom_domains = $domains
        slots          = $slotData
    }
}
$webappData | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\webapps.json" -Encoding UTF8
$manifest.captured_files += "webapps.json"

# ---------------------------------------------------------------------------
# 4. Postgres flex servers
# ---------------------------------------------------------------------------
Log "Capturing Postgres flex servers..."
$pgServers = az postgres flexible-server list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$pgData = @()
foreach ($pg in $pgServers) {
    Log "  $($pg.name)"
    $databases = az postgres flexible-server db list -g $ResourceGroup -s $pg.name -o json 2>$null | ConvertFrom-Json
    $fwRules   = az postgres flexible-server firewall-rule list -g $ResourceGroup -n $pg.name -o json 2>$null | ConvertFrom-Json
    $pgData += @{
        name              = $pg.name
        location          = $pg.location
        sku               = $pg.sku.name
        tier              = $pg.sku.tier
        version           = $pg.version
        admin_user        = $pg.administratorLogin
        storage_gb        = $pg.storage.storageSizeGB
        backup_retention  = $pg.backup.backupRetentionDays
        databases         = ($databases | ForEach-Object { $_.name })
        firewall_rules    = $fwRules
        fqdn              = $pg.fullyQualifiedDomainName
    }
    if (-not $SkipPostgresDump) {
        Log "  pg_dump $($pg.name) ..."
        $dumpDir = "$OutputDir\postgres-dumps\$($pg.name)"
        New-Item -ItemType Directory -Force -Path $dumpDir | Out-Null
        $pgCmd = Get-Command pg_dump -ErrorAction SilentlyContinue
        if (-not $pgCmd) {
            Log "  WARN: pg_dump not on PATH. Skipping dump for $($pg.name). Use -SkipPostgresDump to silence."
        } else {
            foreach ($db in $databases) {
                if ($db.name -in @('postgres','azure_maintenance','azure_sys')) { continue }
                $dumpFile = "$dumpDir\$($db.name).sql"
                Log "    -> $($db.name) -> $dumpFile"
                # Operator must provide PGPASSWORD env var before running this script
                $env:PGHOST     = $pg.fullyQualifiedDomainName
                $env:PGUSER     = $pg.administratorLogin
                $env:PGDATABASE = $db.name
                $env:PGSSLMODE  = "require"
                & pg_dump --no-owner --no-acl --clean --if-exists -f $dumpFile 2>&1 | Add-Content $LogFile
            }
        }
    } else {
        Log "  Postgres data dump SKIPPED (-SkipPostgresDump)"
    }
}
$pgData | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\postgres-flex.json" -Encoding UTF8
$manifest.captured_files += "postgres-flex.json"

# ---------------------------------------------------------------------------
# 5. AI Search
# ---------------------------------------------------------------------------
Log "Capturing AI Search services..."
$searches = az search service list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$searchData = @()
foreach ($svc in $searches) {
    Log "  $($svc.name)"
    # Get admin key for REST API call to list indexes
    $adminKey = az search admin-key show -g $ResourceGroup --service-name $svc.name --query "primaryKey" -o tsv 2>$null
    $indexes = @()
    if ($adminKey) {
        $endpoint = "https://$($svc.name).search.windows.net/indexes?api-version=2023-11-01"
        try {
            $resp = Invoke-RestMethod -Uri $endpoint -Headers @{ "api-key" = $adminKey } -Method GET
            $indexes = $resp.value
        } catch {
            Log "  WARN: failed to list indexes for $($svc.name): $_"
        }
    }
    $searchData += @{
        name       = $svc.name
        location   = $svc.location
        sku        = $svc.sku.name
        replicas   = $svc.replicaCount
        partitions = $svc.partitionCount
        indexes    = $indexes
    }
}
$searchData | ConvertTo-Json -Depth 20 | Out-File "$OutputDir\ai-search.json" -Encoding UTF8
$manifest.captured_files += "ai-search.json"

# ---------------------------------------------------------------------------
# 6. Static Web Apps
# ---------------------------------------------------------------------------
Log "Capturing Static Web Apps..."
$swas = az staticwebapp list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$swaData = @()
foreach ($swa in $swas) {
    Log "  $($swa.name)"
    $hostnames = az staticwebapp hostname list -g $ResourceGroup -n $swa.name -o json 2>$null | ConvertFrom-Json
    $swaData += @{
        name           = $swa.name
        location       = $swa.location
        sku            = $swa.sku.name
        repo_url       = $swa.repositoryUrl
        branch         = $swa.branch
        custom_domains = $hostnames
        default_host   = $swa.defaultHostname
    }
}
$swaData | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\static-web-apps.json" -Encoding UTF8
$manifest.captured_files += "static-web-apps.json"

# ---------------------------------------------------------------------------
# 7. Key Vault (names + binary backups, NOT raw values)
# ---------------------------------------------------------------------------
Log "Capturing Key Vaults..."
$kvs = az keyvault list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
$kvData = @()
foreach ($kv in $kvs) {
    Log "  $($kv.name)"
    $secrets = az keyvault secret list --vault-name $kv.name --query "[].name" -o tsv 2>$null
    $secretNames = @()
    if ($secrets) {
        $secretNames = ($secrets -split "`n" | Where-Object { $_ })
        $backupDir = "$OutputDir\keyvault-backups\$($kv.name)"
        New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
        foreach ($s in $secretNames) {
            $backupFile = "$backupDir\$s.bin"
            Log "    backup secret: $s"
            az keyvault secret backup --vault-name $kv.name --name $s --file $backupFile 2>$null | Out-Null
        }
    }
    $kvData += @{
        name         = $kv.name
        location     = $kv.location
        sku          = $kv.properties.sku.name
        secret_names = $secretNames
    }
}
$kvData | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\keyvault.json" -Encoding UTF8
$manifest.captured_files += "keyvault.json"

# ---------------------------------------------------------------------------
# 8. App Insights + Log Analytics
# ---------------------------------------------------------------------------
Log "Capturing App Insights + Log Analytics..."
$apps = az monitor app-insights component show -g $ResourceGroup -o json 2>$null
if ($apps) {
    az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/components" -o json 2>$null | Out-File "$OutputDir\app-insights.json" -Encoding UTF8
    $manifest.captured_files += "app-insights.json"
}
az monitor log-analytics workspace list -g $ResourceGroup -o json 2>$null | Out-File "$OutputDir\log-analytics.json" -Encoding UTF8
$manifest.captured_files += "log-analytics.json"

# ---------------------------------------------------------------------------
# 9. DNS Zone (BIND export)
# ---------------------------------------------------------------------------
Log "Capturing DNS zones..."
$zones = az network dns zone list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
foreach ($zone in $zones) {
    Log "  $($zone.name)"
    $zoneFile = "$OutputDir\dns-$($zone.name).zone"
    az network dns zone export -g $ResourceGroup -n $zone.name --file-name $zoneFile 2>$null | Out-Null
    $manifest.captured_files += "dns-$($zone.name).zone"
}
$zones | ConvertTo-Json -Depth 10 | Out-File "$OutputDir\dns-zones.json" -Encoding UTF8
$manifest.captured_files += "dns-zones.json"

# ---------------------------------------------------------------------------
# 10. Alert rules + Action groups
# ---------------------------------------------------------------------------
Log "Capturing alert rules + action groups..."
az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" -o json 2>$null `
    | Out-File "$OutputDir\scheduled-query-rules.json" -Encoding UTF8
az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" -o json 2>$null `
    | Out-File "$OutputDir\metric-alerts.json" -Encoding UTF8
az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/actionGroups" -o json 2>$null `
    | Out-File "$OutputDir\action-groups.json" -Encoding UTF8
$manifest.captured_files += @("scheduled-query-rules.json", "metric-alerts.json", "action-groups.json")

# ---------------------------------------------------------------------------
# 11. Full ARM template export (best-effort; some resources skip)
# ---------------------------------------------------------------------------
Log "Capturing full ARM template export (best-effort)..."
az group export -g $ResourceGroup --skip-resource-name-params --skip-all-params 2>$null `
    | Out-File "$OutputDir\arm-template.json" -Encoding UTF8
$manifest.captured_files += "arm-template.json"

# ---------------------------------------------------------------------------
# Write manifest
# ---------------------------------------------------------------------------
$manifest | ConvertTo-Json -Depth 6 | Out-File "$OutputDir\manifest.json" -Encoding UTF8

Log ""
Log "=== snapshot complete ==="
Log "Output: $OutputDir"
Log "Files: $($manifest.captured_files.Count) artifacts + dumps + backups"
Log ""
Log "NEXT STEPS:"
Log "  * To destroy:  .\scripts\destroy-azure.ps1 -SnapshotPath '$OutputDir'"
Log "  * To rebuild:  .\scripts\rebuild-azure.ps1 -SnapshotPath '$OutputDir'"
Log ""
Log "SECURITY:"
Log "  Snapshot contains: app settings, Postgres dumps, Key Vault secret backups."
Log "  Move to a secure location (encrypted disk, vault) if not used immediately."
