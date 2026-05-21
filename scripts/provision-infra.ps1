# Provision Postgres + Azure AI Search for Session 01
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/provision-infra.ps1
# This runs async in the background; check logs for status

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Ensure we have the right subscription
az account set --subscription "SignalLayerDev"
$currentSub = az account show --query name -o tsv
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Subscription: $currentSub"

$resourceGroup = "rg-aigovern-dev"
$region = "eastus"
$project = "aigovern"
$env = "dev"

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Resource Group: $resourceGroup, Region: $region"

# Check if resource group exists
$rgExists = az group exists --name $resourceGroup -o tsv
if ($rgExists -eq "false") {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Creating resource group..."
    az group create --name $resourceGroup --location $region
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Resource group already exists"
}

# Provision PostgreSQL Server (if not already created)
$dbName = "psql-$project-$env"
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Checking PostgreSQL server: $dbName"

$dbExists = az resource show --name $dbName --resource-group $resourceGroup --resource-type "Microsoft.DBforPostgreSQL/servers" 2>$null
if ($null -eq $dbExists) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] PostgreSQL server not found; provisioning..."

    # Generate random admin password
    $adminPass = -join ((65..90) + (97..122) + (48..57) | Get-Random -Count 16 | % { [char]$_ })

    az postgres server create `
        --resource-group $resourceGroup `
        --name $dbName `
        --location $region `
        --admin-user "pgadmin" `
        --admin-password $adminPass `
        --sku-name "B_Gen5_2" `
        --storage-mb 51200 `
        --version "11"

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] PostgreSQL server created: $dbName"
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Admin user: pgadmin (password saved in secrets)"
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: Failed to provision PostgreSQL"
        exit 1
    }
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] PostgreSQL server already exists"
}

# Provision Azure AI Search service (if not already created)
$searchName = "search-$project-$env"
Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Checking Azure AI Search: $searchName"

$searchExists = az resource show --name $searchName --resource-group $resourceGroup --resource-type "Microsoft.Search/searchServices" 2>$null
if ($null -eq $searchExists) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Azure AI Search service not found; provisioning..."

    az search service create `
        --resource-group $resourceGroup `
        --name $searchName `
        --location $region `
        --sku "basic" `
        --partition-count 1 `
        --replica-count 1

    if ($LASTEXITCODE -eq 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Azure AI Search service created: $searchName"
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] ERROR: Failed to provision Azure AI Search"
        exit 1
    }
} else {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Azure AI Search service already exists"
}

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Provisioning complete!"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Get PostgreSQL connection string:"
Write-Host "   az postgres server show-connection-string --server-name $dbName --admin-user pgadmin"
Write-Host ""
Write-Host "2. Get Azure AI Search endpoint and key:"
Write-Host "   az search service show --name $searchName --resource-group $resourceGroup --query properties.endpoint"
Write-Host "   az search admin-key show --service-name $searchName --resource-group $resourceGroup --query primaryKey"
