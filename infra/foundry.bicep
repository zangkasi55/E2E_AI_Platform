// =============================================================================
// foundry.bicep — minimal live AI Foundry stack for the Agentic AI PoC.
// Scope: resource group (rg-agentic-poc-swc, swedencentral).
// Provisions: AI Foundry account (kind=AIServices, project management) + project,
// gpt-4o + gpt-4o-mini deployments, Log Analytics + App Insights (token telemetry),
// Cosmos DB serverless (audit: runs/steps/handoffs/tokens, pk /run_id),
// Key Vault (RBAC), user-assigned managed identity + least-privilege role
// assignments. Deferred (cost): APIM, Purview, AI Search, Defender, Functions.
// Synthetic data only. southeastasia has no gpt-4o quota → swedencentral.
// =============================================================================

@description('Deployment region. swedencentral has gpt-4o quota; southeastasia does not.')
param location string = resourceGroup().location

@description('Resource name prefix.')
param prefix string = 'agpoc'

@description('Environment tag/suffix.')
param env string = 'dev'

@description('Foundry project name (data-plane). Override to match an existing project, e.g. SCBXAIplatformPOC.')
param projectName string = '${prefix}-proj-${env}'

@description('gpt-4o model version.')
param gpt4oVersion string = '2024-11-20'

@description('gpt-4o-mini model version.')
param gpt4oMiniVersion string = '2024-07-18'

@description('GlobalStandard capacity (x1000 TPM) for gpt-4o.')
param gpt4oCapacity int = 30

@description('GlobalStandard capacity (x1000 TPM) for gpt-4o-mini.')
param gpt4oMiniCapacity int = 50

var tags = {
  project: 'agentic-ai-poc'
  env: env
  partner: 'DataX-TechX-Microsoft'
  data: 'synthetic-only'
}

var uniq = uniqueString(resourceGroup().id)
var foundryName = '${prefix}-aifoundry-${env}'
var lawName = '${prefix}-law-${env}'
var appiName = '${prefix}-appi-${env}'
var cosmosName = '${prefix}-cosmos-${env}-${uniq}'
var kvName = take('${prefix}kv${env}${uniq}', 24)
var uamiName = '${prefix}-id-orchestrator-${env}'

// ---- Observability ----------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: appiName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
  }
}

// ---- User-assigned managed identity (orchestrator) --------------------------
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
  tags: tags
}

// ---- AI Foundry account (AIServices) + project ------------------------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: toLower(foundryName)
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Agentic AI PoC'
    description: 'DataX/TechX x Microsoft — credit memo + conversational banking agents.'
  }
}

// ---- Application Insights connection (project telemetry sink) ----------------
// Wires the App Insights component to the Foundry PROJECT as a first-class
// connection so the portal Tracing / Observability surfaces (agent runs, token
// usage, gen_ai spans) light up. Without this connection the project has no
// telemetry sink and the Tracing tab stays empty even when the backend exports
// OTEL spans. category='AppInsights', credential = the AI connection string.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: appiName
  properties: {
    category: 'AppInsights'
    target: appi.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appi.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appi.id
    }
  }
}

// ---- Model deployments (serial: same account cannot deploy in parallel) -----
resource gpt4o 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'gpt-4o'
  sku: { name: 'GlobalStandard', capacity: gpt4oCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o', version: gpt4oVersion }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource gpt4oMini 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'gpt-4o-mini'
  dependsOn: [ gpt4o ]
  sku: { name: 'GlobalStandard', capacity: gpt4oMiniCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o-mini', version: gpt4oMiniVersion }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// ---- Cosmos DB (serverless) — audit trail -----------------------------------
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    enableAutomaticFailover: false
    capabilities: [ { name: 'EnableServerless' } ]
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [ { locationName: location, failoverPriority: 0, isZoneRedundant: false } ]
    disableLocalAuth: false
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: 'agentaudit'
  properties: { resource: { id: 'agentaudit' } }
}

var auditContainers = [ 'runs', 'steps', 'handoffs', 'tokens' ]
resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [for c in auditContainers: {
  parent: cosmosDb
  name: c
  properties: {
    resource: {
      id: c
      partitionKey: { paths: [ '/run_id' ], kind: 'Hash' }
    }
  }
}]

// ---- Key Vault (RBAC authorization) -----------------------------------------
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// ---- RBAC: least-privilege grants to the orchestrator UAMI -------------------
var roleOpenAiUser = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services OpenAI User
var roleKvSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User

resource raOpenAi 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, uami.id, roleOpenAiUser)
  scope: foundry
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleOpenAiUser)
  }
}

resource raKv 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, uami.id, roleKvSecretsUser)
  scope: kv
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleKvSecretsUser)
  }
}

// Cosmos data-plane: Built-in Data Contributor to the UAMI on the account.
resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, uami.id, '00000000-0000-0000-0000-000000000002')
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: uami.properties.principalId
    scope: cosmos.id
  }
}

// ---- Outputs (consumed by the backend live config + Entra wiring) -----------
output foundryAccountResourceId string = foundry.id
output foundryAccountName string = foundry.name
output foundryEndpoint string = foundry.properties.endpoint
output projectName string = project.name
// Data-plane project endpoint consumed by the orchestrator backend
// (FOUNDRY_PROJECT_ENDPOINT) for live agent invocation + tracing.
output foundryProjectEndpoint string = 'https://${toLower(foundryName)}.services.ai.azure.com/api/projects/${project.name}'
output aoaiEndpoint string = 'https://${toLower(foundryName)}.openai.azure.com/'
output gpt4oDeployment string = gpt4o.name
output gpt4oMiniDeployment string = gpt4oMini.name
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output cosmosAccountName string = cosmos.name
output keyVaultName string = kv.name
output keyVaultUri string = kv.properties.vaultUri
output appInsightsConnectionString string = appi.properties.ConnectionString
output logAnalyticsId string = law.id
output orchestratorIdentityClientId string = uami.properties.clientId
output orchestratorIdentityPrincipalId string = uami.properties.principalId
output orchestratorIdentityResourceId string = uami.id
