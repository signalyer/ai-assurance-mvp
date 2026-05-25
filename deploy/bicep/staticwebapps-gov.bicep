// staticwebapps-gov.bicep — Azure Static Web App for V2 CISO Console (Phase 2)
//
// Sibling to staticwebapps.bicep (which provisions the Team Workspace SPA).
// Both modules are intentionally lean: no custom domain binding here — staging
// URL only (swa-aigovern-gov-dev.{N}.azurestaticapps.net). Custom domain
// (gov.aigovern.sandboxhub.co) is a separate Week 5 cutover step per
// docs/plans/V2-PORTAL-SPLIT.md §6.
//
// Region: eastus2 (mandatory — Static Web Apps are not available in eastus,
// per global CLAUDE.md "Static Web Apps exception"). Cross-region to the
// engine in eastus is sub-10ms within the Azure backbone — no functional
// impact.
//
// Build / deploy strategy:
//   cd ciso-console && npm run build
//   swa deploy ./dist --deployment-token "$SWA_GOV_DEPLOYMENT_TOKEN"
// Retrieve the token after first deploy:
//   az staticwebapp secrets list --name swa-aigovern-gov-dev \
//     --resource-group rg-aigovern-dev --query "properties.apiKey" -o tsv

@description('Region for Static Web App. Must be eastus2 (only valid region for our subscription per SWA regional rules).')
@allowed([
  'eastus2'
  'centralus'
  'westus2'
  'westeurope'
  'eastasia'
])
param location string = 'eastus2'

@description('Name of the Static Web App resource (CISO Console SPA — V2 Phase 2).')
param swaName string = 'swa-aigovern-gov-dev'

@description('Pricing tier. Free is sufficient for staging/dev. Standard required only for custom auth, private endpoints, or > 100GB/mo bandwidth.')
@allowed([
  'Free'
  'Standard'
])
param sku string = 'Free'

// ---------------------------------------------------------------------------
// Static Web App resource
// ---------------------------------------------------------------------------
//
// Properties intentionally omitted for the lean-staging path — match the
// Team Workspace module exactly:
//   - repositoryUrl / branch / repositoryToken: deploys come from SWA CLI
//   - buildProperties: Vite build is local, output is ./ciso-console/dist
//   - customDomains: deferred to Week 5 cutover
//
resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: location
  sku: {
    name: sku
    tier: sku
  }
  properties: {
    allowConfigFileUpdates: true
    stagingEnvironmentPolicy: 'Enabled' // PR preview environments (free tier limit: 3)
    enterpriseGradeCdnStatus: 'Disabled'
  }
  tags: {
    project: 'aigovern'
    env: 'dev'
    component: 'ciso-console'
    phase: 'v2-phase-2'
    'managed-by': 'bicep'
  }
}

// ---------------------------------------------------------------------------
// Outputs
// ---------------------------------------------------------------------------

@description('Auto-generated *.azurestaticapps.net hostname for the SWA (the staging URL until Week 5 DNS cutover).')
output defaultHostname string = swa.properties.defaultHostname

@description('Resource ID of the Static Web App (for downstream RBAC / custom domain wiring).')
output swaResourceId string = swa.id

@description('Resource name (for post-deploy az staticwebapp commands).')
output swaName string = swa.name
