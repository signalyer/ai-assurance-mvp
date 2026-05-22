# Bicep IaC — AI Assurance Platform

## Resources deployed

| Resource | Name | Notes |
|---|---|---|
| App Service Plan | `asp-aigovern-dev` | B1 Linux, Python 3.12, ~$13/mo |
| Web App reference | `app-aigovern-dev` | Existing — not re-created |
| Log Analytics workspace | `log-aigovern-prod` | PerGB2018, 30-day retention, eastus |
| Application Insights | `appi-aigovern-prod` | Workspace-based, linked to above |
| 8 KQL alert rules | `alert-*` | See `alerts.bicep` for KQL and thresholds |

## Deploy command

```bash
az deployment group create \
  --resource-group rg-aigovern-dev \
  --template-file deploy/bicep/main.bicep \
  --parameters @deploy/bicep/parameters.dev.json
```

## Post-deploy: inject App Insights connection string

The `appInsightsConnectionString` output is marked `@secure()` and is NOT
printed in deployment output by default. Retrieve and inject it explicitly:

```bash
# 1. Retrieve the connection string from the deployment output
CONNECTION_STRING=$(az deployment group show \
  --resource-group rg-aigovern-dev \
  --name <your-deployment-name> \
  --query "properties.outputs.appInsightsConnectionString.value" \
  -o tsv)

# 2. Inject into the App Service
az webapp config appsettings set \
  --name app-aigovern-dev \
  --resource-group rg-aigovern-dev \
  --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$CONNECTION_STRING"
```

On Windows (PowerShell):

```powershell
$cs = az deployment group show `
  --resource-group rg-aigovern-dev `
  --name <your-deployment-name> `
  --query "properties.outputs.appInsightsConnectionString.value" `
  -o tsv

az webapp config appsettings set `
  --name app-aigovern-dev `
  --resource-group rg-aigovern-dev `
  --settings "APPLICATIONINSIGHTS_CONNECTION_STRING=$cs"
```

## What-if (dry run)

```bash
az deployment group what-if \
  --resource-group rg-aigovern-dev \
  --template-file deploy/bicep/main.bicep \
  --parameters @deploy/bicep/parameters.dev.json
```

## Notes

- `workspaceName=log-aigovern-prod` is intentional — this workspace is being
  provisioned now for future production log routing.
- No secrets appear in `parameters.dev.json`. The App Insights connection
  string is returned as a `@secure()` output and must be injected separately.
- `actionGroupId` defaults to empty (no alerts notifications). Populate with
  an existing Action Group resource ID to enable email/SMS/webhook paging.
