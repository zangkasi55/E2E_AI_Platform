// =============================================================================
// functions.bicep
// Azure Functions (Python v2) — TOOL EXECUTION + DURABLE HITL for the PoC.
//
// Canonical (POC_SPEC.md):
//   Tools host     -> agpoc-func-tools-dev    (executes the 9 catalog tools)
//   Durable host   -> agpoc-func-durable-dev  (HITL orchestration: pause/resume)
//
// Both run on a Linux Consumption plan and use the tool-bridge UAMI for Entra
// access (Cosmos, Search, Key Vault, Service Bus). App settings reference Key
// Vault secrets via @Microsoft.KeyVault(...) and are wired to App Insights.
//
// HITL: the durable app parks an approval on Service Bus `hitl-approvals`
// (sessions = run_id), waits for the Teams reviewer's approve/edit, then resumes.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Resource prefix (canonical: agpoc).')
param prefix string

@description('Environment suffix (canonical: dev).')
param env string

@description('Tools Function App name (canonical: agpoc-func-tools-dev).')
param toolsFunctionAppName string

@description('Durable HITL Function App name (canonical: agpoc-func-durable-dev).')
param durableFunctionAppName string

@description('Tool-bridge user-assigned identity resource ID (from identity.bicep).')
param toolBridgeIdentityId string

@description('Tool-bridge user-assigned identity client ID (for DefaultAzureCredential).')
param toolBridgeClientId string

@description('Tool-bridge user-assigned identity principal ID (for Service Bus RBAC).')
param toolBridgePrincipalId string

@description('App Insights connection string.')
param appInsightsConnectionString string

@description('Key Vault URI for @Microsoft.KeyVault references.')
param keyVaultUri string

@description('Cosmos DB endpoint (audit/state writes).')
param cosmosEndpoint string

@description('Cosmos DB database name.')
param cosmosDatabaseName string

@description('Azure OpenAI endpoint (tool-side model calls).')
param openAiEndpoint string

@description('Azure AI Search endpoint.')
param searchEndpoint string

@description('Service Bus fully-qualified namespace (for Entra Service Bus clients).')
param serviceBusFqdn string

@description('Service Bus namespace name (RBAC scope).')
param serviceBusNamespaceName string

@description('HITL queue name.')
param hitlQueueName string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// -----------------------------------------------------------------------------
// Dedicated Functions RUNTIME storage (AzureWebJobsStorage + Durable task hub).
// This is an implementation detail separate from the canonical DATA store
// `agpocstoragedev`; keeping them apart avoids mixing audit data with runtime
// queues/blobs. Name: agpocfxstordev (<= 24 lc alnum).
// -----------------------------------------------------------------------------
resource funcStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: '${prefix}fxstor${env}'
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

// -----------------------------------------------------------------------------
// Consumption plan (Y1 Dynamic, Linux). For Flex Consumption swap to sku 'FC1'
// + add functionAppConfig.deployment — see deployment-plan.md.
// -----------------------------------------------------------------------------
resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: '${prefix}-func-plan-${env}'
  location: location
  tags: tags
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true // Linux
  }
}

// Storage runtime connection string (key-based, required by the Functions host).
var funcStorageConnString = 'DefaultEndpointsProtocol=https;AccountName=${funcStorage.name};EndpointSuffix=${environment().suffixes.storage};AccountKey=${funcStorage.listKeys().keys[0].value}'

// Shared base app settings. Endpoints are passed as plain values (Entra access
// via the tool-bridge UAMI); only true secrets use Key Vault references.
var baseAppSettings = [
  {
    name: 'FUNCTIONS_EXTENSION_VERSION'
    value: '~4'
  }
  {
    name: 'FUNCTIONS_WORKER_RUNTIME'
    value: 'python'
  }
  {
    name: 'AzureWebJobsStorage'
    value: funcStorageConnString
  }
  {
    name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
    value: appInsightsConnectionString
  }
  {
    // Selects WHICH managed identity DefaultAzureCredential uses at runtime.
    name: 'AZURE_CLIENT_ID'
    value: toolBridgeClientId
  }
  {
    name: 'KEY_VAULT_URI'
    value: keyVaultUri
  }
  {
    name: 'COSMOS_ENDPOINT'
    value: cosmosEndpoint
  }
  {
    name: 'COSMOS_DATABASE'
    value: cosmosDatabaseName
  }
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: openAiEndpoint
  }
  {
    name: 'SEARCH_ENDPOINT'
    value: searchEndpoint
  }
  {
    name: 'SERVICEBUS_FQDN'
    value: serviceBusFqdn
  }
  {
    name: 'HITL_QUEUE'
    value: hitlQueueName
  }
  {
    // EXAMPLE Key Vault reference (resolved by the Functions host via the UAMI).
    name: 'APIM_SUBSCRIPTION_KEY'
    value: '@Microsoft.KeyVault(SecretUri=${keyVaultUri}secrets/apim-subscription-key/)'
  }
]

// -----------------------------------------------------------------------------
// Tools Function App (agpoc-func-tools-dev)
// -----------------------------------------------------------------------------
resource toolsApp 'Microsoft.Web/sites@2023-12-01' = {
  name: toolsFunctionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${toolBridgeIdentityId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: baseAppSettings
    }
  }
}

// -----------------------------------------------------------------------------
// Durable HITL Function App (agpoc-func-durable-dev). Adds the durable task hub
// name; everything else (identity, settings) is shared.
// -----------------------------------------------------------------------------
resource durableApp 'Microsoft.Web/sites@2023-12-01' = {
  name: durableFunctionAppName
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${toolBridgeIdentityId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: concat(baseAppSettings, [
        {
          name: 'DURABLE_TASK_HUB'
          value: 'agpochitl'
        }
      ])
    }
  }
}

// -----------------------------------------------------------------------------
// Service Bus RBAC for the tool-bridge identity (co-located with the queue per
// the note in identity.bicep). Data Owner on the namespace covers send+receive
// for the durable HITL flow. Split into Sender/Receiver for production.
// -----------------------------------------------------------------------------
var serviceBusDataOwnerRoleId = '090c5cfd-751d-490a-894a-3ce6f1109419'

resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}

resource sbToolBridge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: serviceBus
  name: guid(serviceBus.id, toolBridgePrincipalId, serviceBusDataOwnerRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceBusDataOwnerRoleId)
    principalId: toolBridgePrincipalId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics (both apps)
// -----------------------------------------------------------------------------
resource toolsDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: toolsApp
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'FunctionAppLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

@description('Tools Function App resource ID.')
output toolsFunctionAppId string = toolsApp.id

@description('Tools Function App default hostname (https://agpoc-func-tools-dev.azurewebsites.net).')
output toolsFunctionAppHostname string = toolsApp.properties.defaultHostName

@description('Durable HITL Function App resource ID.')
output durableFunctionAppId string = durableApp.id

@description('Durable HITL Function App default hostname.')
output durableFunctionAppHostname string = durableApp.properties.defaultHostName
