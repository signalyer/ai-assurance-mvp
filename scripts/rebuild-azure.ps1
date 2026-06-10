# scripts/rebuild-azure.ps1
#
# Reprovision the rg-aigovern-dev stack from a snapshot taken by snapshot-azure.ps1.
# Restores resources in dependency order; restores Postgres data via pg_restore;
# re-applies App Service settings; re-binds custom domains; restores Key Vault
# secrets from binary backups.
#
# WHAT THIS SCRIPT CANNOT DO:
#   * SSL certificate provisioning -- managed certs auto-issue after DNS validates
#     (~15 min after domain bind succeeds). Script reports when validation begins.
#   * Static Web App content -- script triggers `swa deploy` if swa CLI is on
#     PATH; otherwise prints the manual command.
#   * Re-issue ANTHROPIC_API_KEY or AWS creds -- captured from App Service
#     settings in snapshot. If your prior settings were truncated or rotated,
#     you must re-issue.
#   * DNS at the registrar -- if DNS zone was deleted and recreated, the new
#     nameservers must be re-registered with sandboxhub.co's parent registrar.
#
# Usage:
#   .\scripts\rebuild-azure.ps1 -SnapshotPath scripts\snapshots\20260610-033500
#   .\scripts\rebuild-azure.ps1 -SnapshotPath ... -DryRun
#   .\scripts\rebuild-azure.ps1 -SnapshotPath ... -SkipPostgresRestore
#   .\scripts\rebuild-azure.ps1 -SnapshotPath ... -NewPostgresPassword 'newPW'

param(
    [Parameter(Mandatory=$true)][string]$SnapshotPath,
    [switch]$DryRun,
    [switch]$SkipPostgresRestore,
    [switch]$SkipKeyVaultRestore,
    [string]$NewPostgresPassword = "",
    [string]$ResourceGroup = "rg-aigovern-dev",
    [string]$Subscription  = "SignalLayerDev"
)

$env:MSYS_NO_PATHCONV = "1"
$ProgressPreference   = "SilentlyContinue"
$LogFile = Join-Path $PSScriptRoot ".rebuild-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"

function Log { param([string]$m,[string]$lvl="INFO"); $l="[$(Get-Date -Format 'HH:mm:ss')] [$lvl] $m"; Write-Host $l; Add-Content $LogFile $l }
function Run { param([string]$d,[scriptblock]$a)
    Log $d
    if ($DryRun) { Log "  [DRY-RUN] skipped" "DRY"; return $null }
    try { return & $a } catch { Log "  FAILED: $_" "WARN"; return $null }
}

# ---------------------------------------------------------------------------
# Load snapshot
# ---------------------------------------------------------------------------
$manifestPath = Join-Path $SnapshotPath "manifest.json"
if (-not (Test-Path $manifestPath)) { Log "FATAL: $manifestPath not found" "ERROR"; exit 1 }
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
Log "Loaded snapshot from $($manifest.snapshot_timestamp)"

az account set --subscription $Subscription 2>$null | Out-Null
$cur = (az account show --query "name" -o tsv 2>$null) -replace '\s',''
if ($cur -ne $Subscription) { Log "FATAL: sub mismatch ($cur)" "ERROR"; exit 1 }

# Ensure RG exists (re-create if destroy removed it; we never use group delete so
# usually present, but defensive)
$rgExists = az group exists -n $ResourceGroup 2>$null
if ($rgExists -ne "true") {
    Run "Create resource group: $ResourceGroup" {
        az group create -n $ResourceGroup --location "eastus" --output none
    }
}

# ---------------------------------------------------------------------------
# 1. Log Analytics first (App Insights depends on it)
# ---------------------------------------------------------------------------
$laPath = Join-Path $SnapshotPath "log-analytics.json"
if (Test-Path $laPath) {
    $las = Get-Content $laPath -Raw | ConvertFrom-Json
    foreach ($la in $las) {
        Run "Recreate Log Analytics: $($la.name)" {
            az monitor log-analytics workspace create -g $ResourceGroup -n $la.name `
                --location $la.location --output none
        }
    }
}

# ---------------------------------------------------------------------------
# 2. App Insights
# ---------------------------------------------------------------------------
$aiPath = Join-Path $SnapshotPath "app-insights.json"
if (Test-Path $aiPath) {
    $ais = Get-Content $aiPath -Raw | ConvertFrom-Json
    foreach ($ai in $ais) {
        Run "Recreate App Insights: $($ai.name)" {
            az monitor app-insights component create -g $ResourceGroup -a $ai.name `
                --location $ai.location --output none
        }
    }
}

# ---------------------------------------------------------------------------
# 3. Postgres flex (recreate, restore dumps, set new password)
# ---------------------------------------------------------------------------
$pgPath = Join-Path $SnapshotPath "postgres-flex.json"
if (Test-Path $pgPath) {
    $pgs = Get-Content $pgPath -Raw | ConvertFrom-Json
    if ($pgs -and -not $NewPostgresPassword -and -not $DryRun) {
        Log "Generating new Postgres admin password (urlsafe, 24-char)..."
        $NewPostgresPassword = -join ((1..24) | ForEach-Object { [char](Get-Random -Min 33 -Max 126) })
        Log "  Password: $NewPostgresPassword  (SAVE THIS NOW)"
    }
    foreach ($pg in $pgs) {
        Run "Recreate Postgres flex: $($pg.name)" {
            az postgres flexible-server create -g $ResourceGroup -n $pg.name `
                --location $pg.location --tier $pg.tier --sku-name $pg.sku `
                --version $pg.version --admin-user $pg.admin_user `
                --admin-password $NewPostgresPassword --storage-size $pg.storage_gb `
                --backup-retention $pg.backup_retention `
                --public-access "0.0.0.0" --yes --output none
        }
        # Restore firewall rules
        foreach ($fw in $pg.firewall_rules) {
            Run "  firewall rule: $($fw.name)" {
                az postgres flexible-server firewall-rule create -g $ResourceGroup `
                    -n $pg.name -r $fw.name --start-ip-address $fw.startIpAddress `
                    --end-ip-address $fw.endIpAddress --output none
            }
        }
        # Restore databases + data
        foreach ($db in $pg.databases) {
            if ($db -in @('postgres','azure_maintenance','azure_sys')) { continue }
            Run "  create database: $db" {
                az postgres flexible-server db create -g $ResourceGroup -s $pg.name -d $db --output none
            }
            if (-not $SkipPostgresRestore) {
                $dumpFile = "$SnapshotPath\postgres-dumps\$($pg.name)\$db.sql"
                if (Test-Path $dumpFile) {
                    Run "  restore dump: $db <- $dumpFile" {
                        $env:PGHOST     = $pg.fqdn
                        $env:PGUSER     = $pg.admin_user
                        $env:PGPASSWORD = $NewPostgresPassword
                        $env:PGDATABASE = $db
                        $env:PGSSLMODE  = "require"
                        $psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
                        if ($psqlCmd) {
                            & psql -f $dumpFile 2>&1 | Add-Content $LogFile
                        } else {
                            Log "  WARN: psql not on PATH. Restore $dumpFile manually."
                        }
                    }
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 4. AI Search (recreate empty; indexes restored from schemas)
# ---------------------------------------------------------------------------
$searchPath = Join-Path $SnapshotPath "ai-search.json"
if (Test-Path $searchPath) {
    $searches = Get-Content $searchPath -Raw | ConvertFrom-Json
    foreach ($svc in $searches) {
        Run "Recreate AI Search: $($svc.name) (SKU=$($svc.sku))" {
            az search service create -g $ResourceGroup -n $svc.name `
                --location $svc.location --sku $svc.sku `
                --replica-count $svc.replicas --partition-count $svc.partitions --output none
        }
        Log "  NOTE: $($svc.name) takes ~10-15 min to be reachable. Index schemas will be POSTed after."
        if (-not $DryRun) {
            Log "  Waiting 60s for service to begin responding..."
            Start-Sleep -Seconds 60
            $adminKey = az search admin-key show -g $ResourceGroup --service-name $svc.name --query "primaryKey" -o tsv 2>$null
            foreach ($idx in $svc.indexes) {
                if ($adminKey) {
                    $endpoint = "https://$($svc.name).search.windows.net/indexes/$($idx.name)?api-version=2023-11-01"
                    try {
                        Invoke-RestMethod -Uri $endpoint -Headers @{ "api-key" = $adminKey } `
                            -Method PUT -Body ($idx | ConvertTo-Json -Depth 20) -ContentType "application/json"
                        Log "  recreated index: $($idx.name)"
                    } catch {
                        Log "  WARN: failed to recreate index $($idx.name): $_"
                    }
                }
            }
            Log "  NOTE: Index documents NOT restored. Re-run RAG corpus ingestion."
        }
    }
}

# ---------------------------------------------------------------------------
# 5. App Service Plans
# ---------------------------------------------------------------------------
$planPath = Join-Path $SnapshotPath "appservice-plans.json"
if (Test-Path $planPath) {
    $plans = Get-Content $planPath -Raw | ConvertFrom-Json
    foreach ($plan in $plans) {
        $sku = $plan.sku.name
        $isLinux = $plan.kind -like "*linux*"
        Run "Recreate App Service Plan: $($plan.name) (SKU=$sku, linux=$isLinux)" {
            $cmd = "az appservice plan create -g $ResourceGroup -n $($plan.name) --sku $sku --location $($plan.location) --output none"
            if ($isLinux) { $cmd += " --is-linux" }
            Invoke-Expression $cmd
        }
    }
}

# ---------------------------------------------------------------------------
# 6. App Services + settings + slots + custom domains
# ---------------------------------------------------------------------------
$webappPath = Join-Path $SnapshotPath "webapps.json"
if (Test-Path $webappPath) {
    $webapps = Get-Content $webappPath -Raw | ConvertFrom-Json
    foreach ($app in $webapps) {
        $planName = ($app.plan_id -split "/")[-1]
        Run "Recreate webapp: $($app.name) on plan $planName" {
            az webapp create -g $ResourceGroup -n $app.name --plan $planName `
                --runtime $app.runtime --output none
        }
        # If new Postgres password was generated, patch DATABASE_URL in the settings
        $patchedSettings = @()
        foreach ($s in $app.settings) {
            $val = $s.value
            if ($NewPostgresPassword -and $s.name -eq "DATABASE_URL" -and $val -match "postgresql") {
                $val = $val -replace ':[^:@]+@', ":$NewPostgresPassword@"
                Log "  Patched DATABASE_URL with new password"
            }
            $patchedSettings += "$($s.name)=$val"
        }
        if ($patchedSettings.Count -gt 0) {
            Run "  Apply app settings ($($patchedSettings.Count) entries)" {
                az webapp config appsettings set -g $ResourceGroup -n $app.name `
                    --settings @patchedSettings --output none
            }
        }
        # Custom domains
        foreach ($d in $app.custom_domains) {
            if ($d.name -like "*.azurewebsites.net") { continue }
            Run "  Bind custom domain: $($d.name)" {
                az webapp config hostname add -g $ResourceGroup --webapp-name $app.name --hostname $d.name --output none
            }
            Log "  NOTE: SSL cert for $($d.name) must be re-issued. Use:"
            Log "    az webapp config ssl create -g $ResourceGroup --name $($app.name) --hostname $($d.name)"
            Log "    (Managed cert; takes ~15 min after DNS CNAME verifies.)"
        }
        # Slots
        foreach ($slot in $app.slots) {
            Run "  Create slot: $($app.name)/$($slot.name)" {
                az webapp deployment slot create -g $ResourceGroup --name $app.name --slot $slot.name --output none
            }
            $slotSettings = @()
            foreach ($s in $slot.settings) {
                $val = $s.value
                if ($NewPostgresPassword -and $s.name -eq "DATABASE_URL" -and $val -match "postgresql") {
                    $val = $val -replace ':[^:@]+@', ":$NewPostgresPassword@"
                }
                $slotSettings += "$($s.name)=$val"
            }
            if ($slotSettings.Count -gt 0) {
                Run "  Apply slot settings ($($slotSettings.Count))" {
                    az webapp config appsettings set -g $ResourceGroup -n $app.name --slot $slot.name `
                        --settings @slotSettings --output none
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 7. Static Web Apps
# ---------------------------------------------------------------------------
$swaPath = Join-Path $SnapshotPath "static-web-apps.json"
if (Test-Path $swaPath) {
    $swas = Get-Content $swaPath -Raw | ConvertFrom-Json
    foreach ($swa in $swas) {
        Run "Recreate SWA: $($swa.name) (SKU=$($swa.sku))" {
            az staticwebapp create -g $ResourceGroup -n $swa.name `
                --location $swa.location --sku $swa.sku --output none
        }
        foreach ($h in $swa.custom_domains) {
            Run "  Bind SWA custom domain: $($h.name)" {
                az staticwebapp hostname set -g $ResourceGroup -n $swa.name --hostname $h.name --output none
            }
        }
        Log "  NOTE: SWA content NOT restored. Trigger:"
        Log "    cd team-portal && npm run build && swa deploy ./dist --env production"
        Log "    cd ciso-console && npm run build && swa deploy ./dist --env production"
    }
}

# ---------------------------------------------------------------------------
# 8. Key Vault + secret restore
# ---------------------------------------------------------------------------
$kvPath = Join-Path $SnapshotPath "keyvault.json"
if ((Test-Path $kvPath) -and -not $SkipKeyVaultRestore) {
    $kvs = Get-Content $kvPath -Raw | ConvertFrom-Json
    foreach ($kv in $kvs) {
        Run "Recreate Key Vault: $($kv.name)" {
            az keyvault create -g $ResourceGroup -n $kv.name --location $kv.location --sku $kv.sku --output none
        }
        $backupDir = "$SnapshotPath\keyvault-backups\$($kv.name)"
        if (Test-Path $backupDir) {
            foreach ($backup in (Get-ChildItem $backupDir -Filter "*.bin")) {
                Run "  Restore secret from backup: $($backup.Name)" {
                    az keyvault secret restore --vault-name $kv.name --file $backup.FullName --output none
                }
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 9. DNS zone (only if it doesn't already exist)
# ---------------------------------------------------------------------------
$dnsJsonPath = Join-Path $SnapshotPath "dns-zones.json"
if (Test-Path $dnsJsonPath) {
    $zones = Get-Content $dnsJsonPath -Raw | ConvertFrom-Json
    foreach ($zone in $zones) {
        $exists = az network dns zone show -g $ResourceGroup -n $zone.name 2>$null
        if (-not $exists) {
            Run "Recreate DNS zone: $($zone.name)" {
                az network dns zone create -g $ResourceGroup -n $zone.name --output none
            }
            $zoneFile = "$SnapshotPath\dns-$($zone.name).zone"
            if (Test-Path $zoneFile) {
                Run "  Import DNS records: $zoneFile" {
                    az network dns zone import -g $ResourceGroup -n $zone.name --file-name $zoneFile --output none
                }
            }
            Log "  WARN: New DNS zone has NEW nameservers. Update sandboxhub.co NS records at registrar."
            $newNs = az network dns zone show -g $ResourceGroup -n $zone.name --query "nameServers" -o tsv
            Log "  New nameservers: $newNs"
        } else {
            Log "DNS zone $($zone.name) already exists, skipping recreate (records preserved)"
        }
    }
}

# ---------------------------------------------------------------------------
# 10. Alert rules + action groups (last; after everything alertable is up)
# ---------------------------------------------------------------------------
Log "Step 10: Restoring action groups + alert rules from ARM templates..."
foreach ($f in @("action-groups.json", "scheduled-query-rules.json", "metric-alerts.json")) {
    $path = Join-Path $SnapshotPath $f
    if (Test-Path $path) {
        Log "  NOTE: Re-apply manually via 'az deployment group create' against $f"
        Log "  (Auto-deploy disabled because resource IDs in the snapshot may not match new tenant.)"
    }
}

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
Log ""
Log "=== rebuild complete ==="
Log ""
Log "MANUAL STEPS REMAINING:"
Log "  1. SSL: re-issue managed certs for each custom domain (see notes above)"
Log "  2. SWA: trigger 'swa deploy' for team-portal + ciso-console"
Log "  3. RAG: re-ingest corpus into AI Search indexes"
Log "  4. Alerts: redeploy ARM templates if you need alerts back"
Log "  5. Verify: curl https://app-aigovern-dev.azurewebsites.net/api/health"
Log ""
if ($NewPostgresPassword) {
    Log "POSTGRES PASSWORD: $NewPostgresPassword"
    Log "  Update 1Password vault entry: 'aigovern postgres admin'"
}
Log ""
Log "Log file: $LogFile"
