// main.bicep — Top-level deployment for AI Assurance Platform (dev)
// Composes: App Insights + Log Analytics workspace (NEW) +
//           8 KQL alerts (NEW).
//           App Service Plan and Web App are referenced as EXISTING resources —
//           they were provisioned in westus2; this template does not re-create them.
//
// Deploy command:
//   az deployment group create \
//     --resource-group rg-aigovern-dev \
//     --template-file deploy/bicep/main.bicep \
//     --parameters @deploy/bicep/parameters.dev.json
//
// Post-deploy: inject the App Insights connection string into the App Service.
// See deploy/bicep/README.md for the full post-deploy command.

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Azure region for NEW resources (Log Analytics workspace + App Insights).')
param location string = 'eastus'

@description('Name of the Log Analytics workspace to create. Named -prod intentionally.')
param workspaceName string = 'log-aigovern-prod'

@description('Name of the Application Insights component to create.')
param appInsightsName string = 'appi-aigovern-prod'

@description('Name of the existing App Service web app (reference only, not created).')
param appName string = 'app-aigovern-dev'

@description('Optional Action Group resource ID for alert notifications. Leave empty to skip.')
param actionGroupId string = ''

// ---- Alerts module toggle (S46, default OFF) -------------------------------
// Azure Monitor metric-alert resources have an immutable `scopes[]` property.
// Once created, any redeploy that re-emits the scope fails with
// `ScopeUpdateNotAllowed`. Default false so routine `az deployment group create`
// runs no-op against existing alerts. Set true only on first provision or when
// explicitly modifying alert configs (and expect to recreate, not update).
@description('Toggle: deploy the 8 KQL alerts module. Default false because alert scope is immutable post-create.')
param deployAlerts bool = false

// ---- V2 Phase 2 — Team Workspace SWA (opt-in, default OFF) -----------------

@description('Toggle: provision the V2 Team Workspace Static Web App. Defaults to false to keep existing deploys idempotent.')
param deployTeamPortal bool = false

@description('Region for the Team Workspace SWA. Must be eastus2 per the global Static Web App regional rule.')
param teamPortalLocation string = 'eastus2'

@description('Resource name for the Team Workspace Static Web App.')
param teamPortalSwaName string = 'swa-aigovern-portal-dev'

@description('Pricing tier for the Team Workspace SWA. Free is sufficient for staging.')
param teamPortalSwaSku string = 'Free'

// ---- V2 Phase 2 — CISO Console SWA (opt-in, default OFF) -------------------
// Session 44 — sibling of deployTeamPortal. Mirrors the same toggle pattern
// so the two SPAs can be provisioned independently (e.g. portal first to
// shake out the SWA-CLI deploy path, then gov when ready).

@description('Toggle: provision the V2 CISO Console Static Web App. Defaults to false to keep existing deploys idempotent.')
param deployCisoConsole bool = false

@description('Region for the CISO Console SWA. Must be eastus2 per the global Static Web App regional rule.')
param cisoConsoleLocation string = 'eastus2'

@description('Resource name for the CISO Console Static Web App.')
param cisoConsoleSwaName string = 'swa-aigovern-gov-dev'

@description('Pricing tier for the CISO Console SWA. Free is sufficient for staging.')
param cisoConsoleSwaSku string = 'Free'

// ---- A15 / S46 — App Service staging slot (opt-in, default OFF) ------------
// Adds a `staging` slot to the existing app-aigovern-dev web app for
// zero-downtime deploys (deploy → smoke staging → swap). Requires the ASP
// to be Standard tier or higher; current P2v3 satisfies this. The slot
// inherits its parent web app's location (westus2), not the eastus default
// of the alerts/AppInsights resources.

@description('Toggle: provision the staging deployment slot on the existing web app. Defaults to false.')
param deployStagingSlot bool = false

@description('Name of the existing web app to attach the staging slot to.')
param webAppName string = 'app-aigovern-dev'

@description('Region of the existing web app. Slot inherits parent location; must match.')
param webAppLocation string = 'westus2'

@description('Name of the slot. Convention: app URL becomes {webAppName}-{slotName}.azurewebsites.net.')
param stagingSlotName string = 'staging'

// ---------------------------------------------------------------------------
// Existing resource references (read-only — do NOT create)
// ---------------------------------------------------------------------------

// Suppress unused warning: appName param is documented for operators even though
// the existing resource block is removed to keep the what-if clean.
// If you need to update app settings, target the web app directly via CLI.

// ---------------------------------------------------------------------------
// App Insights + Log Analytics workspace (NEW resources)
// ---------------------------------------------------------------------------
module appInsightsModule 'appinsights.bicep' = {
  name: 'appinsights-deploy'
  params: {
    workspaceName: workspaceName
    appInsightsName: appInsightsName
    location: location
  }
}

// ---------------------------------------------------------------------------
// 8 KQL Alerts (NEW resources)
// ---------------------------------------------------------------------------
module alertsModule 'alerts.bicep' = if (deployAlerts) {
  name: 'alerts-deploy'
  params: {
    workspaceId: appInsightsModule.outputs.workspaceId
    location: location
    actionGroupId: actionGroupId
  }
}

// ---------------------------------------------------------------------------
// V2 Phase 2 — Team Workspace Static Web App (conditional)
// ---------------------------------------------------------------------------
//
// Opt-in via `deployTeamPortal=true`. Defaults to false so existing deploys
// (App Insights + alerts only) remain a no-op what-if. Region forced to
// eastus2 per SWA regional rule (not the eastus default of the rest of the
// stack). NO custom DNS binding here — Week 5 cutover concern per
// docs/plans/V2-PORTAL-SPLIT.md §6.
module teamPortalSwa 'staticwebapps.bicep' = if (deployTeamPortal) {
  name: 'team-portal-swa-deploy'
  params: {
    swaName: teamPortalSwaName
    location: teamPortalLocation
    sku: teamPortalSwaSku
  }
}

// ---------------------------------------------------------------------------
// V2 Phase 2 — CISO Console Static Web App (conditional, Session 44)
// ---------------------------------------------------------------------------
// Opt-in via `deployCisoConsole=true`. Independent of `deployTeamPortal` so
// either SPA can be provisioned first. Same constraints: eastus2 region, no
// custom DNS binding (Week 5 cutover handles gov.aigovern.sandboxhub.co).
module cisoConsoleSwa 'staticwebapps-gov.bicep' = if (deployCisoConsole) {
  name: 'ciso-console-swa-deploy'
  params: {
    swaName: cisoConsoleSwaName
    location: cisoConsoleLocation
    sku: cisoConsoleSwaSku
  }
}

// ---------------------------------------------------------------------------
// A15 / S46 — Staging deployment slot on the existing web app (conditional)
// ---------------------------------------------------------------------------
// Slot is a child resource of the existing site. We reference the parent as
// `existing` to avoid re-emitting site properties on every deploy (the site
// was provisioned out-of-band). Slot keeps minimal explicit properties —
// httpsOnly + serverFarmId inheritance — so app-setting overrides ("sticky"
// settings like V2_APEX_REDIRECT) are managed via az CLI post-provision.

resource existingWebApp 'Microsoft.Web/sites@2023-12-01' existing = {
  name: webAppName
}

resource stagingSlot 'Microsoft.Web/sites/slots@2023-12-01' = if (deployStagingSlot) {
  parent: existingWebApp
  name: stagingSlotName
  location: webAppLocation
  properties: {
    serverFarmId: existingWebApp.properties.serverFarmId
    httpsOnly: true
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

@secure()
@description('Application Insights connection string. Inject into App Service app settings as APPLICATIONINSIGHTS_CONNECTION_STRING.')
output appInsightsConnectionString string = appInsightsModule.outputs.appInsightsConnectionString

@description('Resource ID of the Log Analytics workspace.')
output workspaceId string = appInsightsModule.outputs.workspaceId

@description('Reminder: inject the connection string into the web app after deploy.')
output postDeployNote string = 'Run: az webapp config appsettings set --name ${appName} --resource-group rg-aigovern-dev --settings APPLICATIONINSIGHTS_CONNECTION_STRING=$(az deployment group show ... --query properties.outputs.appInsightsConnectionString.value -o tsv)'

@description('Default *.azurestaticapps.net hostname for the Team Workspace SWA. Empty string when deployTeamPortal=false.')
output teamPortalHostname string = deployTeamPortal ? teamPortalSwa.outputs.defaultHostname : ''

@description('Default *.azurestaticapps.net hostname for the CISO Console SWA. Empty string when deployCisoConsole=false.')
output cisoConsoleHostname string = deployCisoConsole ? cisoConsoleSwa.outputs.defaultHostname : ''

@description('Hostname of the staging slot. Empty string when deployStagingSlot=false.')
output stagingSlotHostname string = deployStagingSlot ? stagingSlot.properties.defaultHostName : ''
