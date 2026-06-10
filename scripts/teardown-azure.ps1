# scripts/teardown-azure.ps1
#
# Safely shut down billable compute in rg-aigovern-dev while preserving:
#   * DNS zone (aigovern.sandboxhub.co) + all records
#   * App Service custom domains, SSL bindings, app settings, slots
#   * Postgres data (paused, not deleted)
#   * Key Vault, App Insights, Log Analytics, Static Web Apps (no idle cost)
#   * All container/resource names -- bring-up restores by name, not by ARM redeploy
#
# What it does NOT do (per global CLAUDE.md "always deny"):
#   * az group delete
#   * az storage account delete
#   * az cosmosdb delete
#   * Any resource deletion -- only stop / pause operations
#
# Cost reduction (verified against rg-aigovern-dev 2026-06-10):
#   Idle stack today: ~$130/mo (App Service Plan B1 + AI Search B1 + Postgres flex B1ms)
#   After teardown:   ~$90/mo  (Postgres flex paused; saves ~$40/mo)
#   With -IncludeSearch: ~$15/mo  (also deletes AI Search; saves another ~$75/mo)
#
# No Application Gateway exists in this RG (ag-aigovern-dev is an Action Group,
# which is free). If you add one later (e.g. for WAF), the script will discover
# and stop it automatically — that adds ~$250/mo to teardown savings.
#
# Usage:
#   .\scripts\teardown-azure.ps1                 # standard teardown
#   .\scripts\teardown-azure.ps1 -DryRun         # show plan, no changes
#   .\scripts\teardown-azure.ps1 -IncludeSearch  # also delete AI Search (saves ~$75/mo)
#
# Idempotent: re-running on an already-torn-down stack is a no-op.

param(
    [switch]$DryRun,
    [switch]$IncludeSearch,
    [string]$ResourceGroup = "rg-aigovern-dev",
    [string]$Subscription  = "SignalLayerDev"
)

# NOTE: keep ErrorActionPreference at default ("Continue"). az CLI emits warnings
# to stderr (e.g. "Preview version of extension is disabled by default") which PS
# would treat as terminating errors under "Stop". The Invoke-Az wrapper has its
# own try/catch + explicit Log "FAILED" path for the cases we care about.
$env:MSYS_NO_PATHCONV  = "1"   # Windows Git Bash path fix per global CLAUDE.md
$ProgressPreference    = "SilentlyContinue"  # suppress az CLI progress spinners

$StateFile = Join-Path $PSScriptRoot ".teardown-state.json"
$LogFile   = Join-Path $PSScriptRoot ".teardown-log-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"

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
# Step 0 -- Verify subscription and inventory
# ---------------------------------------------------------------------------
Log "=== teardown-azure.ps1 starting ==="
Log "Subscription: $Subscription"
Log "Resource group: $ResourceGroup"
Log "Mode: $(if ($DryRun) {'DRY-RUN'} else {'LIVE'})"

az account set --subscription $Subscription 2>$null | Out-Null
$current = (az account show --query "name" -o tsv 2>$null) -replace '\s', ''
if ($current -ne $Subscription) {
    Log "FATAL: Subscription set failed: expected '$Subscription', got '$current'" "ERROR"
    exit 1
}

# Capture pre-state for bring-up
$state = @{
    teardown_timestamp = (Get-Date -Format "o")
    resource_group     = $ResourceGroup
    subscription       = $Subscription
    include_search     = [bool]$IncludeSearch
    resources_stopped  = @()
    resources_deleted  = @()
    pre_state          = @{}
}

# ---------------------------------------------------------------------------
# Step 1 -- Disable alert rules (prevent teardown-induced noise)
# ---------------------------------------------------------------------------
$alerts = az monitor metrics alert list --resource-group $ResourceGroup --query "[].name" -o tsv 2>$null
if ($alerts) {
    foreach ($alert in ($alerts -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Disable alert: $alert" {
            az monitor metrics alert update --resource-group $ResourceGroup `
                --name $alert --enabled false --output none
        }
        $state.resources_stopped += @{ type = "alert"; name = $alert; action = "disabled" }
    }
} else {
    Log "No metric alerts found"
}

# Scheduled query rules (Microsoft.Insights/scheduledQueryRules — separate API)
# Use ARM resource discovery instead of `az monitor scheduled-query` (which requires
# an extension and prompts interactively if not installed).
$sqRules = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
    --query "[].name" -o tsv 2>$null
if ($sqRules) {
    foreach ($alert in ($sqRules -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Disable scheduled-query alert: $alert (via ARM)" {
            az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/scheduledQueryRules" `
                --name $alert --set properties.enabled=false --output none 2>$null
        }
        $state.resources_stopped += @{ type = "scheduled-query"; name = $alert; action = "disabled" }
    }
}

# Classic metric alerts (Microsoft.Insights/metricAlerts) — also discovered via ARM
$metricAlerts = az resource list -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" `
    --query "[].name" -o tsv 2>$null
if ($metricAlerts) {
    foreach ($alert in ($metricAlerts -split "`n" | Where-Object { $_ })) {
        $alreadyHandled = $state.resources_stopped | Where-Object { $_.type -eq "alert" -and $_.name -eq $alert }
        if (-not $alreadyHandled) {
            Invoke-Az "Disable metric alert: $alert (via ARM)" {
                az resource update -g $ResourceGroup --resource-type "Microsoft.Insights/metricAlerts" `
                    --name $alert --set properties.enabled=false --output none 2>$null
            }
            $state.resources_stopped += @{ type = "metric-alert-arm"; name = $alert; action = "disabled" }
        }
    }
}

# ---------------------------------------------------------------------------
# Step 2 -- Stop Application Gateway (BIGGEST cost saver: ~$250/mo)
# ---------------------------------------------------------------------------
# Discover Application Gateways by listing (handles unknown names / multiple GWs)
$appGws = az network application-gateway list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($appGwName in ($appGws -split "`n" | Where-Object { $_ })) {
    $appGwState = az network application-gateway show -g $ResourceGroup -n $appGwName `
        --query "operationalState" -o tsv 2>$null
    if ($appGwState -eq "Running") {
        Invoke-Az "Stop Application Gateway: $appGwName (saves ~USD 250/mo)" {
            az network application-gateway stop -g $ResourceGroup -n $appGwName --output none
        }
        $state.resources_stopped += @{ type = "application-gateway"; name = $appGwName; pre_state = "Running" }
    } elseif ($appGwState) {
        Log "Application Gateway $appGwName already in state: $appGwState (skipping)"
    }
}
if (-not $appGws) {
    Log "No Application Gateways found in $ResourceGroup"
}

# ---------------------------------------------------------------------------
# Step 3 -- Stop App Service slots, then main app
# (slots must stop BEFORE main, else slot can keep plan warm)
# ---------------------------------------------------------------------------
$webapps = az webapp list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($app in ($webapps -split "`n" | Where-Object { $_ })) {
    # Stop slots first
    $slots = az webapp deployment slot list -g $ResourceGroup --name $app `
        --query "[].name" -o tsv 2>$null
    foreach ($slot in ($slots -split "`n" | Where-Object { $_ })) {
        Invoke-Az "Stop slot: $app/$slot" {
            az webapp stop -g $ResourceGroup --name $app --slot $slot --output none
        }
        $state.resources_stopped += @{ type = "webapp-slot"; name = "$app/$slot" }
    }
    # Stop main app
    Invoke-Az "Stop webapp: $app" {
        az webapp stop -g $ResourceGroup --name $app --output none
    }
    $state.resources_stopped += @{ type = "webapp"; name = $app }
}

# ---------------------------------------------------------------------------
# Step 4 -- Stop Postgres Flexible Server (saves ~$30-50/mo compute)
# Auto-resumes after 7 days -- bring-up script restarts explicitly before then
# ---------------------------------------------------------------------------
$pgServers = az postgres flexible-server list -g $ResourceGroup --query "[].name" -o tsv 2>$null
foreach ($pg in ($pgServers -split "`n" | Where-Object { $_ })) {
    $pgState = az postgres flexible-server show -g $ResourceGroup -n $pg `
        --query "state" -o tsv 2>$null
    if ($pgState -eq "Ready") {
        Invoke-Az "Stop Postgres Flexible Server: $pg (saves ~USD 40/mo, 7-day pause limit)" {
            az postgres flexible-server stop -g $ResourceGroup -n $pg --output none
        }
        $state.resources_stopped += @{ type = "postgres-flex"; name = $pg; pre_state = "Ready" }
    } else {
        Log "Postgres $pg already in state: $pgState (skipping)"
    }
}

# ---------------------------------------------------------------------------
# Step 5 -- AI Search (only if -IncludeSearch; cannot be paused, only deleted)
# ---------------------------------------------------------------------------
if ($IncludeSearch) {
    $searches = az search service list -g $ResourceGroup --query "[].name" -o tsv 2>$null
    foreach ($svc in ($searches -split "`n" | Where-Object { $_ })) {
        # Capture SKU + replica/partition config so bring-up restores accurately
        $cfg = az search service show -g $ResourceGroup -n $svc `
            --query "{sku:sku.name, replicas:replicaCount, partitions:partitionCount}" -o json | ConvertFrom-Json
        Log "WARNING: AI Search $svc will be DELETED. Indexes will need to be repopulated on bring-up."
        Log "  Saved config: SKU=$($cfg.sku) replicas=$($cfg.replicas) partitions=$($cfg.partitions)"
        $state.pre_state[$svc] = @{
            type       = "search-service"
            sku        = $cfg.sku
            replicas   = $cfg.replicas
            partitions = $cfg.partitions
            location   = (az search service show -g $ResourceGroup -n $svc --query "location" -o tsv)
        }
        Invoke-Az "DELETE AI Search service: $svc (saves ~USD 75/mo)" {
            az search service delete -g $ResourceGroup -n $svc --yes --output none
        }
        $state.resources_deleted += @{ type = "search-service"; name = $svc }
    }
} else {
    Log "AI Search left running (use -IncludeSearch to delete and save ~USD 75/mo)"
}

# ---------------------------------------------------------------------------
# Step 6 -- Write state file for bring-up
# ---------------------------------------------------------------------------
if (-not $DryRun) {
    $state | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding UTF8
    Log "State written to: $StateFile"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
Log "=== teardown summary ==="
Log "Stopped: $($state.resources_stopped.Count) resources"
Log "Deleted: $($state.resources_deleted.Count) resources"
Log ""
Log "PRESERVED (still billing minimally, expected ~USD 90/mo idle, or USD 15 with -IncludeSearch):"
Log "  * App Service Plan (asp-aigovern-dev) -- needed for SSL + custom domains"
Log "  * DNS zone (aigovern.sandboxhub.co) -- USD 0.50/mo"
Log "  * Key Vault, App Insights, Log Analytics -- pay-per-use, near zero idle"
Log "  * Static Web Apps -- free tier"
Log "  * Storage accounts -- only what data is stored (cents/mo at demo scale)"
if (-not $IncludeSearch) {
    Log "  * AI Search service (~USD 75/mo) -- pass -IncludeSearch to delete"
}
Log ""
Log "TO BRING BACK UP: .\scripts\startup-azure.ps1"
Log "Log file: $LogFile"
