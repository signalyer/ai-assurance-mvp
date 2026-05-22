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
module alertsModule 'alerts.bicep' = {
  name: 'alerts-deploy'
  params: {
    workspaceId: appInsightsModule.outputs.workspaceId
    location: location
    actionGroupId: actionGroupId
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
