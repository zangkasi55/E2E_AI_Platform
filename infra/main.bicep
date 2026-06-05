// =============================================================================
// main.bicep — Agentic AI Platform PoC (DataX/TechX x Microsoft, SCBX context)
// Single composition root. SUBSCRIPTION-SCOPED so it can:
//   - create the canonical resource group `rg-agentic-poc-sea`
//   - enable Defender for Cloud plans (subscription-scoped)
// All workload resources are deployed INTO the resource group via `scope: rg`.
//
// Canonical names / region / tags come from POC_SPEC.md. Deploy order is
// expressed through module dependencies (and documented in infra/README.md):
//   observability -> storage/keyvault/cosmos/openai/search/servicebus
//                 -> identity (RBAC) -> apim -> functions -> containerapps
//                 -> purview -> defender
//
// Deploy:
//   az deployment sub create -l southeastasia \
//     -f infra/main.bicep -p infra/main.bicepparam
// =============================================================================

targetScope = 'subscription'

// -----------------------------------------------------------------------------
// Core parameters (canonical defaults; override in main.bicepparam)
// -----------------------------------------------------------------------------
@description('Azure region. Canonical: southeastasia (Singapore), Thailand-nearest.')
param location string = 'southeastasia'

@description('Resource group name. Canonical: rg-agentic-poc-sea.')
param resourceGroupName string = 'rg-agentic-poc-sea'

@description('Resource name prefix. Canonical: agpoc.')
param prefix string = 'agpoc'

@description('Environment suffix. Canonical: dev.')
param env string = 'dev'

@description('Common tags applied to every resource (canonical set).')
param tags object = {
  project: 'agentic-poc'
  env: 'dev'
  owner: 'datax-techx'
}

@description('APIM publisher email (notifications).')
param apimPublisherEmail string = 'datax-techx@example.com'

@description('Orchestrator container image (overridden by backend.yml after first push).')
param orchestratorImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Reuse an existing tenant Purview account instead of creating a new one.')
param useExistingPurview bool = false

@description('Resource group containing the existing Purview account when useExistingPurview=true.')
param existingPurviewResourceGroupName string = ''

@description('Existing Purview account name when useExistingPurview=true.')
param existingPurviewAccountName string = ''

// Defender toggles (subscription-scoped; default to safe/cheap for a shared sub).
@description('Enable Standard CSPM (paid). Default false = Free CSPM.')
param enableStandardCspm bool = false
@description('Enable paid Defender plans (Key Vault / Storage / AI).')
param enableDefenderPaidPlans bool = true

// -----------------------------------------------------------------------------
// Canonical resource names (POC_SPEC.md table). Centralised for one-glance audit.
// -----------------------------------------------------------------------------
var names = {
  logAnalytics: '${prefix}-law-${env}' // agpoc-law-dev
  appInsights: '${prefix}-appi-${env}' // agpoc-appi-dev
  keyVault: '${prefix}-kv-${env}' // agpoc-kv-dev
  storage: '${prefix}storage${env}' // agpocstoragedev (no dashes)
  cosmos: '${prefix}-cosmos-${env}' // agpoc-cosmos-dev
  openai: '${prefix}-aoai-${env}' // agpoc-aoai-dev
  search: '${prefix}-search-${env}' // agpoc-search-dev
  serviceBus: '${prefix}-sb-${env}' // agpoc-sb-dev
  apim: '${prefix}-apim-${env}' // agpoc-apim-dev
  funcTools: '${prefix}-func-tools-${env}' // agpoc-func-tools-dev
  funcDurable: '${prefix}-func-durable-${env}' // agpoc-func-durable-dev
  acaOrch: '${prefix}-aca-orch-${env}' // agpoc-aca-orch-dev
  purview: '${prefix}-purview-${env}' // agpoc-purview-dev
}

// -----------------------------------------------------------------------------
// Resource group (the only thing created at subscription scope besides Defender)
// -----------------------------------------------------------------------------
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

// =============================================================================
// PHASE 1 — Observability (everyone wires diagnostics here)
// =============================================================================
module observability 'modules/observability.bicep' = {
  name: 'observability'
  scope: rg
  params: {
    location: location
    tags: tags
    logAnalyticsName: names.logAnalytics
    appInsightsName: names.appInsights
  }
}

// =============================================================================
// PHASE 2 — Foundational data + secrets + messaging (parallel)
// =============================================================================
module storage 'modules/storage.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    location: location
    tags: tags
    storageAccountName: names.storage
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

module keyvault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    location: location
    tags: tags
    keyVaultName: names.keyVault
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  scope: rg
  params: {
    location: location
    tags: tags
    cosmosAccountName: names.cosmos
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

module openai 'modules/openai.bicep' = {
  name: 'openai'
  scope: rg
  params: {
    location: location
    tags: tags
    openAiAccountName: names.openai
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

module search 'modules/search.bicep' = {
  name: 'search'
  scope: rg
  params: {
    location: location
    tags: tags
    searchServiceName: names.search
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

module servicebus 'modules/servicebus.bicep' = {
  name: 'servicebus'
  scope: rg
  params: {
    location: location
    tags: tags
    serviceBusNamespaceName: names.serviceBus
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

// =============================================================================
// PHASE 3 — Identity + least-privilege RBAC (needs Phase 2 resources to exist)
// =============================================================================
module identity 'modules/identity.bicep' = {
  name: 'identity'
  scope: rg
  params: {
    location: location
    tags: tags
    prefix: prefix
    env: env
    keyVaultName: keyvault.outputs.keyVaultName
    cosmosAccountName: cosmos.outputs.cosmosAccountName
    openAiAccountName: openai.outputs.openAiAccountName
    searchServiceName: search.outputs.searchServiceName
    storageAccountName: storage.outputs.storageAccountName
  }
}

// =============================================================================
// PHASE 4 — APIM tool bridge (needs App Insights + the Functions backend URL)
// Functions host URL is deterministic from its name, so APIM can deploy first.
// =============================================================================
module apim 'modules/apim.bicep' = {
  name: 'apim'
  scope: rg
  params: {
    location: location
    tags: tags
    apimName: names.apim
    publisherEmail: apimPublisherEmail
    toolsBackendUrl: 'https://${names.funcTools}.azurewebsites.net/api'
    appInsightsId: observability.outputs.appInsightsId
    appInsightsInstrumentationKey: observability.outputs.appInsightsInstrumentationKey
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

// =============================================================================
// PHASE 5 — Functions (tool execution + durable HITL)
// =============================================================================
module functions 'modules/functions.bicep' = {
  name: 'functions'
  scope: rg
  params: {
    location: location
    tags: tags
    prefix: prefix
    env: env
    toolsFunctionAppName: names.funcTools
    durableFunctionAppName: names.funcDurable
    toolBridgeIdentityId: identity.outputs.toolBridgeIdentityId
    toolBridgeClientId: identity.outputs.toolBridgeClientId
    toolBridgePrincipalId: identity.outputs.toolBridgePrincipalId
    appInsightsConnectionString: observability.outputs.appInsightsConnectionString
    keyVaultUri: keyvault.outputs.keyVaultUri
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    openAiEndpoint: openai.outputs.openAiEndpoint
    searchEndpoint: search.outputs.searchEndpoint
    serviceBusFqdn: servicebus.outputs.serviceBusFqdn
    serviceBusNamespaceName: servicebus.outputs.serviceBusNamespaceName
    hitlQueueName: servicebus.outputs.queueName
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

// =============================================================================
// PHASE 6 — Container Apps (FastAPI orchestrator)
// =============================================================================
module containerapps 'modules/containerapps.bicep' = {
  name: 'containerapps'
  scope: rg
  params: {
    location: location
    tags: tags
    prefix: prefix
    env: env
    orchestratorAppName: names.acaOrch
    orchestratorIdentityId: identity.outputs.orchestratorIdentityId
    orchestratorClientId: identity.outputs.orchestratorClientId
    containerImage: orchestratorImage
    appInsightsConnectionString: observability.outputs.appInsightsConnectionString
    logAnalyticsName: names.logAnalytics
    keyVaultUri: keyvault.outputs.keyVaultUri
    cosmosEndpoint: cosmos.outputs.cosmosEndpoint
    cosmosDatabaseName: cosmos.outputs.databaseName
    openAiEndpoint: openai.outputs.openAiEndpoint
    searchEndpoint: search.outputs.searchEndpoint
    apimGatewayUrl: apim.outputs.apimGatewayUrl
    toolApiPath: apim.outputs.toolApiPath
  }
}

// =============================================================================
// PHASE 7 — Purview (data governance + PII scan of synthetic storage)
// =============================================================================
module purview 'modules/purview.bicep' = {
  name: 'purview'
  scope: rg
  params: {
    location: location
    tags: tags
    purviewAccountName: useExistingPurview ? existingPurviewAccountName : names.purview
    useExistingPurview: useExistingPurview
    existingPurviewResourceGroupName: existingPurviewResourceGroupName
    storageAccountName: storage.outputs.storageAccountName
    logAnalyticsId: observability.outputs.logAnalyticsId
  }
}

// =============================================================================
// PHASE 8 — Defender for Cloud (SUBSCRIPTION SCOPE — no `scope: rg`)
// =============================================================================
module defender 'modules/defender.bicep' = {
  name: 'defender'
  // No scope -> deploys at the subscription scope of this template.
  params: {
    enableStandardCspm: enableStandardCspm
    enableKeyVaultPlan: enableDefenderPaidPlans
    enableStoragePlan: enableDefenderPaidPlans
    enableAiPlan: enableDefenderPaidPlans
  }
}

// -----------------------------------------------------------------------------
// Composed outputs — the endpoints/IDs the app + CI/CD need.
// -----------------------------------------------------------------------------
output resourceGroup string = rg.name
output appInsightsConnectionString string = observability.outputs.appInsightsConnectionString
output keyVaultUri string = keyvault.outputs.keyVaultUri
output cosmosEndpoint string = cosmos.outputs.cosmosEndpoint
output openAiEndpoint string = openai.outputs.openAiEndpoint
output searchEndpoint string = search.outputs.searchEndpoint
output apimGatewayUrl string = apim.outputs.apimGatewayUrl
output toolBridgeUrl string = '${apim.outputs.apimGatewayUrl}/${apim.outputs.toolApiPath}'
output orchestratorFqdn string = containerapps.outputs.orchestratorFqdn
output toolsFunctionApp string = functions.outputs.toolsFunctionAppHostname
output durableFunctionApp string = functions.outputs.durableFunctionAppHostname
output serviceBusFqdn string = servicebus.outputs.serviceBusFqdn
output purviewCatalogEndpoint string = purview.outputs.purviewCatalogEndpoint
output purviewStudioUrl string = purview.outputs.purviewStudioUrl
output orchestratorClientId string = identity.outputs.orchestratorClientId
output toolBridgeClientId string = identity.outputs.toolBridgeClientId
output uiClientId string = identity.outputs.uiClientId
