# Bicep IaC — AI Assurance Platform

## Resources deployed

| Resource | Name | Notes |
|---|---|---|
| App Service Plan | `asp-aigovern-dev` | P2v3 Linux (PremiumV3), Python 3.12, ~$146/mo. Upgraded from B1 pre-S46 to support slots. |
| Web App reference | `app-aigovern-dev` | Existing — not re-created. westus2. |
| Staging slot (opt-in) | `app-aigovern-dev/slots/staging` | A15 / S46 — zero-downtime deploys via swap. Off by default; set `deployStagingSlot=true` to provision. Requires Standard+ ASP tier (P2v3 ✓). |
| Log Analytics workspace | `log-aigovern-prod` | PerGB2018, 30-day retention, eastus |
| Application Insights | `appi-aigovern-prod` | Workspace-based, linked to above |
| 8 KQL alert rules (opt-in) | `alert-*` | One-shot. Default off. Set `deployAlerts=true` only on first provision or when explicitly modifying alert configs. See `alerts.bicep`. |
| Static Web App (opt-in) | `swa-aigovern-portal-dev` | V2 Phase 2 Team Workspace SPA. **eastus2** (regional rule). Off by default — set `deployTeamPortal=true` to provision. See `staticwebapps.bicep`. |

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

## V2 Phase 2 — Team Workspace SWA (opt-in)

The Team Workspace Static Web App is gated by `deployTeamPortal=true` in
`parameters.dev.json`. Defaults to `false` so existing what-if/deploys
remain a no-op for ops who haven't yet rolled out V2.

### Provision the SWA (one-time)

```powershell
# 1. Set the deployTeamPortal flag to true in parameters.dev.json
#    (or override on the CLI as below)

az deployment group create `
  --resource-group rg-aigovern-dev `
  --template-file deploy/bicep/main.bicep `
  --parameters @deploy/bicep/parameters.dev.json `
  --parameters deployTeamPortal=true

# 2. Capture the staging hostname (e.g. polite-rock-123.4.azurestaticapps.net)
$hostname = az deployment group show `
  --resource-group rg-aigovern-dev `
  --name <your-deployment-name> `
  --query "properties.outputs.teamPortalHostname.value" -o tsv

# 3. Retrieve the deployment token for SWA CLI (stored as the apiKey secret)
$token = az staticwebapp secrets list `
  --name swa-aigovern-portal-dev `
  --resource-group rg-aigovern-dev `
  --query "properties.apiKey" -o tsv
```

### Deploy team-portal/ build artifact

```powershell
cd team-portal
npm install
npm run build           # outputs ./dist
swa deploy ./dist --env production --deployment-token $token
```

The SPA is reachable at `https://$hostname` until the Week-5 DNS cutover
binds `portal.aigovern.sandboxhub.co` (see
`docs/plans/V2-PORTAL-SPLIT.md` §6).

## Notes

- `workspaceName=log-aigovern-prod` is intentional — this workspace is being
  provisioned now for future production log routing.
- No secrets appear in `parameters.dev.json`. The App Insights connection
  string is returned as a `@secure()` output and must be injected separately.
- `actionGroupId` defaults to empty (no alerts notifications). Populate with
  an existing Action Group resource ID to enable email/SMS/webhook paging.
- **Alerts module is one-shot.** Azure Monitor metric-alert `scopes[]` is
  immutable after creation; redeploying with `deployAlerts=true` against
  existing alerts fails with `ScopeUpdateNotAllowed`. Default is `false`.
  Set `--parameters deployAlerts=true` only on first provision or when
  intentionally recreating alert configs (delete the existing alerts first
  via `az monitor scheduled-query delete`). Routine `main.bicep` redeploys
  for SWA / App Insights changes should leave `deployAlerts=false`.
- The Team Workspace SWA is in **eastus2** while the rest of the stack is in
  **eastus**. This is mandatory per the Static Web App regional rule — SWAs
  are not available in eastus. Cross-region SWA → API latency is sub-10ms
  within the Azure backbone (see V2-PORTAL-SPLIT.md §9).
