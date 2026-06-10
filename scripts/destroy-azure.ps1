# scripts/destroy-azure.ps1
#
# Delete every billable resource in rg-aigovern-dev INDIVIDUALLY (not via
# `az group delete`, which is banned by global CLAUDE.md). Default behavior
# preserves the DNS zone (changing nameservers requires registrar action).
#
# REQUIRES a snapshot. Run snapshot-azure.ps1 first or the script refuses.
# This is intentional: deletion is irreversible without the snapshot.
#
# SAFETY GATES (must pass all):
#   1. -SnapshotPath must exist + have manifest.json
#   2. Snapshot must be < 4 hours old (unless -AcceptStaleSnapshot)
#   3. Operator must type the literal string "DELETE EVERYTHING" when prompted
#   4. -DryRun shows what would happen without doing it
#
# Usage:
#   .\scripts\destroy-azure.ps1 -SnapshotPath scripts\snapshots\20260610-033500
#   .\scripts\destroy-azure.ps1 -SnapshotPath ... -DryRun
#   .\scripts\destroy-azure.ps1 -SnapshotPath ... -DeleteDnsZone        # DANGEROUS
#   .\scripts\destroy-azure.ps1 -SnapshotPath ... -DeleteKeyVault        # uses soft-delete
#   .\scripts\destroy-azure.ps1 -SnapshotPath ... -AcceptStaleSnapshot

param(
    [Parameter(Mandatory=$true)][string]$SnapshotPath,
    [switch]$DryRun,
    [switch]$DeleteDnsZone,
    [switch]$DeleteKeyVault,
    [switch]$AcceptStaleSnapshot,
    [string]$ResourceGroup = "rg-aigovern-dev",
    [string]$Subscription  = "SignalLayerDev"
)

$env:MSYS_NO_PATHCONV = "1"
$ProgressPreference   = "SilentlyContinue"
$LogFile = Join-Path $PSScriptRoot ".destroy-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"

function Log { param([string]$m,[string]$lvl="INFO"); $l="[$(Get-Date -Format 'HH:mm:ss')] [$lvl] $m"; Write-Host $l; Add-Content $LogFile $l }
function Run { param([string]$d,[scriptblock]$a)
    Log $d
    if ($DryRun) { Log "  [DRY-RUN] skipped" "DRY"; return }
    try { & $a } catch { Log "  FAILED: $_" "WARN" }
}

# ---------------------------------------------------------------------------
# Safety gate 1: snapshot exists
# ---------------------------------------------------------------------------
$manifestPath = Join-Path $SnapshotPath "manifest.json"
if (-not (Test-Path $manifestPath)) {
    Log "FATAL: snapshot manifest not found at $manifestPath" "ERROR"
    Log "Run snapshot-azure.ps1 first." "ERROR"
    exit 1
}
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
Log "Snapshot found: timestamp=$($manifest.snapshot_timestamp), captured_by=$($manifest.captured_by)"

# ---------------------------------------------------------------------------
# Safety gate 2: snapshot age
# ---------------------------------------------------------------------------
$snapAge = (Get-Date) - [DateTime]::Parse($manifest.snapshot_timestamp)
if ($snapAge.TotalHours -gt 4 -and -not $AcceptStaleSnapshot) {
    Log "FATAL: snapshot is $([int]$snapAge.TotalHours) hours old (>4h limit)" "ERROR"
    Log "Re-snapshot or pass -AcceptStaleSnapshot if you accept the drift risk." "ERROR"
    exit 1
}
Log "Snapshot age: $([int]$snapAge.TotalMinutes) minutes (OK)"

# ---------------------------------------------------------------------------
# Subscription check
# ---------------------------------------------------------------------------
az account set --subscription $Subscription 2>$null | Out-Null
$cur = (az account show --query "name" -o tsv 2>$null) -replace '\s',''
if ($cur -ne $Subscription) { Log "FATAL: sub mismatch ($cur)" "ERROR"; exit 1 }

# ---------------------------------------------------------------------------
# Safety gate 3: explicit consent string (skipped in -DryRun)
# ---------------------------------------------------------------------------
if (-not $DryRun) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host " ABOUT TO DELETE ALL BILLABLE RESOURCES IN: $ResourceGroup" -ForegroundColor Red
    Write-Host "================================================================" -ForegroundColor Red
    Write-Host "Snapshot:        $SnapshotPath"
    Write-Host "DNS zone:        $(if ($DeleteDnsZone) {'WILL BE DELETED'} else {'preserved'})"
    Write-Host "Key Vault:       $(if ($DeleteKeyVault) {'WILL BE DELETED (soft-delete recoverable for 90d)'} else {'preserved'})"
    Write-Host "Recovery via:    .\scripts\rebuild-azure.ps1 -SnapshotPath '$SnapshotPath'"
    Write-Host ""
    Write-Host "Type the literal string 'DELETE EVERYTHING' to proceed:" -ForegroundColor Yellow
    $consent = Read-Host
    if ($consent -ne "DELETE EVERYTHING") {
        Log "Consent string mismatch. Aborting." "ERROR"
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Order of deletion: most dependent first, then dependencies
#   1. App Service slots + apps (depends on plan)
#   2. App Service Plans
#   3. Postgres flex (independent)
#   4. AI Search (independent)
#   5. Static Web Apps (independent)
#   6. Alert rules + Action groups (avoids fire-during-delete)
#   7. App Insights (depends on Log Analytics)
#   8. Log Analytics
#   9. Key Vault (only if -DeleteKeyVault)
#  10. DNS zone (only if -DeleteDnsZone)
# ---------------------------------------------------------------------------

# Step 0: Disable alerts FIRST so they don't fire mid-delete
Log "Step 0: Disabling alerts..."
$sqRules = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" --query "[].name" -o tsv 2>$null
foreach ($a in ($sqRules -split "`n" | Where-Object { $_ })) {
    Run "Disable scheduled-query: $a" {
        az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
            --name $a --set properties.enabled=false --output none 2>$null
    }
}

# Step 1: webapp slots + apps
Log "Step 1: Deleting App Services..."
$webapps = az webapp list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($app in ($webapps -split "`n" | Where-Object { $_ })) {
    $slots = az webapp deployment slot list -g $ResourceGroup --name $app --query "[].name" -o tsv 2>$null
    foreach ($slot in ($slots -split "`n" | Where-Object { $_ })) {
        Run "Delete slot: $app/$slot" {
            az webapp deployment slot delete -g $ResourceGroup --name $app --slot $slot --output none
        }
    }
    Run "Delete webapp: $app" {
        az webapp delete -g $ResourceGroup --name $app --keep-empty-plan true --output none
    }
}

# Step 2: App Service Plans
Log "Step 2: Deleting App Service Plans..."
$plans = az appservice plan list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($plan in ($plans -split "`n" | Where-Object { $_ })) {
    Run "Delete plan: $plan" {
        az appservice plan delete -g $ResourceGroup --name $plan --yes --output none
    }
}

# Step 3: Postgres flex
Log "Step 3: Deleting Postgres flex servers..."
$pgs = az postgres flexible-server list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($pg in ($pgs -split "`n" | Where-Object { $_ })) {
    Run "Delete Postgres flex: $pg" {
        az postgres flexible-server delete -g $ResourceGroup -n $pg --yes --output none
    }
}

# Step 4: AI Search
Log "Step 4: Deleting AI Search services..."
$searches = az search service list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($svc in ($searches -split "`n" | Where-Object { $_ })) {
    Run "Delete AI Search: $svc" {
        az search service delete -g $ResourceGroup -n $svc --yes --output none
    }
}

# Step 5: Static Web Apps
Log "Step 5: Deleting Static Web Apps..."
$swas = az staticwebapp list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($swa in ($swas -split "`n" | Where-Object { $_ })) {
    Run "Delete SWA: $swa" {
        az staticwebapp delete -g $ResourceGroup -n $swa --yes --output none
    }
}

# Step 6: Alert rules + Action groups
Log "Step 6: Deleting alert rules + action groups..."
foreach ($a in ($sqRules -split "`n" | Where-Object { $_ })) {
    Run "Delete scheduled-query: $a" {
        az resource delete -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" --name $a 2>$null
    }
}
$metricAlerts = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" --query "[].name" -o tsv 2>$null
foreach ($a in ($metricAlerts -split "`n" | Where-Object { $_ })) {
    Run "Delete metric alert: $a" {
        az resource delete -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" --name $a 2>$null
    }
}
$actionGroups = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/actionGroups" --query "[].name" -o tsv 2>$null
foreach ($a in ($actionGroups -split "`n" | Where-Object { $_ })) {
    Run "Delete action group: $a" {
        az monitor action-group delete -g $ResourceGroup -n $a --output none 2>$null
    }
}

# Step 7-8: App Insights + Log Analytics
Log "Step 7-8: Deleting App Insights + Log Analytics..."
$ais = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/components" --query "[].name" -o tsv 2>$null
foreach ($ai in ($ais -split "`n" | Where-Object { $_ })) {
    Run "Delete App Insights: $ai" {
        az monitor app-insights component delete -g $ResourceGroup -a $ai --output none 2>$null
    }
}
$las = az monitor log-analytics workspace list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($la in ($las -split "`n" | Where-Object { $_ })) {
    Run "Delete Log Analytics: $la (forces permanent delete)" {
        az monitor log-analytics workspace delete -g $ResourceGroup -n $la --yes --force true --output none 2>$null
    }
}

# Step 9: Key Vault (optional, soft-delete)
if ($DeleteKeyVault) {
    Log "Step 9: Deleting Key Vaults (90-day soft-delete recoverable)..."
    $kvs = az keyvault list -g $ResourceGroup --query "[].name" -o tsv 2>$null
    foreach ($kv in ($kvs -split "`n" | Where-Object { $_ })) {
        Run "Delete Key Vault: $kv" {
            az keyvault delete -g $ResourceGroup -n $kv --output none
        }
    }
} else {
    Log "Step 9: SKIPPED (use -DeleteKeyVault to also remove vaults)"
}

# Step 10: DNS zone (optional, last)
if ($DeleteDnsZone) {
    Log "Step 10: Deleting DNS zones (registrar NS records WILL BREAK)..."
    $zones = az network dns zone list -g $ResourceGroup --query "[].name" -o tsv 2>$null
    foreach ($zone in ($zones -split "`n" | Where-Object { $_ })) {
        Run "Delete DNS zone: $zone" {
            az network dns zone delete -g $ResourceGroup -n $zone --yes --output none
        }
    }
} else {
    Log "Step 10: SKIPPED (DNS zones preserved -- use -DeleteDnsZone to also remove)"
}

# Final inventory
Log ""
Log "=== destroy complete ==="
Log "Remaining resources in $ResourceGroup :"
az resource list -g $ResourceGroup --query "[].{name:name, type:type}" -o table | Tee-Object -FilePath $LogFile -Append
Log ""
Log "TO REBUILD: .\scripts\rebuild-azure.ps1 -SnapshotPath '$SnapshotPath'"
