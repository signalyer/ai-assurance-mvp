# scripts/startup-azure.ps1
#
# Bring everything back online after teardown-azure.ps1 paused the stack.
# Reads scripts/.teardown-state.json (written by teardown) and reverses each
# action in dependency order:
#   1. Postgres first (app needs DB before it starts answering)
#   2. AI Search (if deleted -- recreate at original SKU)
#   3. Application Gateway
#   4. App Service main app, then slots
#   5. Re-enable alerts last (after everything is healthy)
#
# Usage:
#   .\scripts\startup-azure.ps1                # standard bring-up
#   .\scripts\startup-azure.ps1 -DryRun        # show plan, no changes
#   .\scripts\startup-azure.ps1 -SkipHealthCheck   # don't wait for /api/health
#
# Total wall-clock: ~3-6 minutes typical.
#   * Postgres start: ~60-120s
#   * App Gateway start: ~30-90s
#   * Webapp warm-up: ~30-90s (cold start cooldown)
#   * AI Search create (if -IncludeSearch was used): ~10-15 min -- accept the wait

param(
    [switch]$DryRun,
    [switch]$SkipHealthCheck,
    [string]$ResourceGroup = "rg-aigovern-dev",
    [string]$Subscription  = "SignalLayerDev",
    [string]$HealthUrl     = "https://app-aigovern-dev.azurewebsites.net/api/health"
)

# See teardown-azure.ps1 for ErrorActionPreference rationale.
$env:MSYS_NO_PATHCONV  = "1"
$ProgressPreference    = "SilentlyContinue"

$StateFile = Join-Path $PSScriptRoot ".teardown-state.json"
$LogFile   = Join-Path $PSScriptRoot ".startup-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"

function Log {
    param([string]$Msg, [string]$Level = "INFO")
    $line = "[$(Get-Date -Format 'HH:mm:ss')] [$Level] $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Invoke-Az {
    param([string]$Description, [scriptblock]$Action)
    Log $Description
    if ($DryRun) {
        Log "  [DRY-RUN] skipped" "DRY"
        return $null
    }
    try {
        return & $Action
    } catch {
        Log "  FAILED: $_" "WARN"
        return $null
    }
}

# ---------------------------------------------------------------------------
# Step 0 -- Load teardown state
# ---------------------------------------------------------------------------
Log "=== startup-azure.ps1 starting ==="

if (-not (Test-Path $StateFile)) {
    Log "WARNING: $StateFile not found. Running in 'recovery mode' -- will discover stopped resources by querying Azure."
    $state = $null
} else {
    $state = Get-Content -Path $StateFile -Raw | ConvertFrom-Json
    Log "Loaded state from teardown at $($state.teardown_timestamp)"
    Log "Stopped count: $($state.resources_stopped.Count), Deleted count: $($state.resources_deleted.Count)"
}

az account set --subscription $Subscription 2>$null | Out-Null
$current = (az account show --query "name" -o tsv 2>$null) -replace '\s', ''
if ($current -ne $Subscription) {
    Log "FATAL: Subscription set failed: expected '$Subscription', got '$current'" "ERROR"
    exit 1
}

# ---------------------------------------------------------------------------
# Step 1 -- Start Postgres first (App Service depends on it)
# ---------------------------------------------------------------------------
$pgServers = az postgres flexible-server list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($pg in ($pgServers -split "`n" | Where-Object { $_ })) {
    $pgState = az postgres flexible-server show -g $ResourceGroup -n $pg --query "state" -o tsv 2>$null
    if ($pgState -eq "Stopped") {
        Invoke-Az "Start Postgres Flexible Server: $pg" {
            az postgres flexible-server start -g $ResourceGroup -n $pg --output none
        }
    } else {
        Log "Postgres $pg already in state: $pgState (skipping start)"
    }
}

# ---------------------------------------------------------------------------
# Step 2 -- Recreate AI Search if it was deleted
# ---------------------------------------------------------------------------
if ($state) {
    foreach ($deleted in $state.resources_deleted) {
        if ($deleted.type -eq "search-service") {
            $name = $deleted.name
            $cfg = $state.pre_state.$name
            if (-not $cfg) {
                Log "ERROR: no pre_state config for deleted search service $name -- skipping" "ERROR"
                continue
            }
            Invoke-Az "Recreate AI Search: $name (SKU=$($cfg.sku), location=$($cfg.location))" {
                az search service create -g $ResourceGroup -n $name `
                    --sku $cfg.sku --location $cfg.location `
                    --replica-count $cfg.replicas --partition-count $cfg.partitions `
                    --output none
            }
            Log "  NOTE: $name has been recreated empty. Re-run RAG ingestion to repopulate indexes."
            Log "  NOTE: Service takes ~10-15 min to be fully ready."
        }
    }
}

# ---------------------------------------------------------------------------
# Step 3 -- Start Application Gateway
# ---------------------------------------------------------------------------
$appGws = az network application-gateway list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($appGwName in ($appGws -split "`n" | Where-Object { $_ })) {
    $appGwState = az network application-gateway show -g $ResourceGroup -n $appGwName `
        --query "operationalState" -o tsv 2>$null
    if ($appGwState -eq "Stopped") {
        Invoke-Az "Start Application Gateway: $appGwName" {
            az network application-gateway start -g $ResourceGroup -n $appGwName --output none
        }
    } elseif ($appGwState) {
        Log "Application Gateway $appGwName already in state: $appGwState (skipping start)"
    }
}

# ---------------------------------------------------------------------------
# Step 4 -- Start App Service main apps, then slots
# (main FIRST so slot inherits a warm plan)
# ---------------------------------------------------------------------------
$webapps = az webapp list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($app in ($webapps -split "`n" | Where-Object { $_ })) {
    Invoke-Az "Start webapp: $app" {
        az webapp start -g $ResourceGroup --name $app --output none
    }
    $slots = az webapp deployment slot list -g $ResourceGroup --name $app `
        --query "[].name" -o tsv 2>$null
    foreach ($slot in ($slots -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Start slot: $app/$slot" {
            az webapp start -g $ResourceGroup --name $app --slot $slot --output none
        }
    }
}

# ---------------------------------------------------------------------------
# Step 5 -- Wait for /api/health to be reachable + ready (cold-start cooldown)
# ---------------------------------------------------------------------------
if (-not $SkipHealthCheck -and -not $DryRun) {
    Log "Waiting for $HealthUrl to return status=ready..."
    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 10 -ErrorAction Stop
            if ($resp.status -eq "ready") {
                Log "  Engine ready. SHA: $($resp.sha)"
                $ready = $true
                break
            } else {
                Log "  Status: $($resp.status), waiting..."
            }
        } catch {
            Log "  Not reachable yet, waiting 10s..."
        }
        Start-Sleep -Seconds 10
    }
    if (-not $ready) {
        Log "WARNING: Engine did not report ready within 5 min. Check App Service logs." "WARN"
    }
}

# ---------------------------------------------------------------------------
# Step 6 -- Re-enable alerts LAST (after everything is healthy)
# ---------------------------------------------------------------------------
if ($state) {
    foreach ($r in $state.resources_stopped) {
        if ($r.type -eq "alert" -or $r.type -eq "metric-alert-arm") {
            Invoke-Az "Re-enable metric alert: $($r.name)" {
                az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" `
                    --name $r.name --set properties.enabled=true --output none 2>$null
            }
        } elseif ($r.type -eq "scheduled-query") {
            Invoke-Az "Re-enable scheduled-query: $($r.name)" {
                az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
                    --name $r.name --set properties.enabled=true --output none 2>$null
            }
        }
    }
} else {
    Log "No state file -- re-enabling ALL alerts found in resource group via ARM"
    $sqRules = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
        --query "[].name" -o tsv 2>$null
    foreach ($alert in ($sqRules -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Re-enable scheduled-query: $alert" {
            az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
                --name $alert --set properties.enabled=true --output none 2>$null
        }
    }
    $metricAlerts = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" `
        --query "[].name" -o tsv 2>$null
    foreach ($alert in ($metricAlerts -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Re-enable metric alert: $alert" {
            az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" `
                --name $alert --set properties.enabled=true --output none 2>$null
        }
    }
}

# ---------------------------------------------------------------------------
# Step 7 -- Archive the state file (so next teardown starts clean)
# ---------------------------------------------------------------------------
if (-not $DryRun -and (Test-Path $StateFile)) {
    $archive = "$StateFile.restored-$(Get-Date -Format 'yyyyMMdd-HHmmss').json"
    Move-Item -Path $StateFile -Destination $archive
    Log "Archived state file -> $archive"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Log "=== startup summary ==="
Log "Stack should now be fully operational."
Log ""
Log "VERIFY:"
Log "  * Engine: $HealthUrl"
Log "  * Login:  https://aigovern.sandboxhub.co/login (as demo-ciso)"
Log "  * If AI Search was recreated: re-run RAG corpus ingestion"
Log ""
Log "Log file: $LogFile"
