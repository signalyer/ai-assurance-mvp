// appinsights.bicep — Log Analytics workspace + Application Insights component
// Called as a module from main.bicep.
// Outputs the App Insights connection string as a @secure() value.

@description('Name of the Log Analytics workspace to create.')
param workspaceName string

@description('Name of the Application Insights component to create.')
param appInsightsName string

@description('Azure region for both resources.')
param location string

// ---------------------------------------------------------------------------
// Log Analytics workspace
// ---------------------------------------------------------------------------
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Application Insights — workspace-based (classic mode is retired)
// ---------------------------------------------------------------------------
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------
@secure()
output appInsightsConnectionString string = appInsights.properties.ConnectionString

output workspaceId string = logAnalyticsWorkspace.id
output appInsightsId string = appInsights.id
