// =============================================================================
// identity.bicep
// Per-agent WORKLOAD IDENTITY model + least-privilege RBAC for the PoC.
//
// Canonical (POC_SPEC.md): Entra app regs `agpoc-orchestrator`,
// `agpoc-tool-bridge`, `agpoc-ui`. This module provisions the matching
// USER-ASSIGNED MANAGED IDENTITIES (UAMIs) and wires least-privilege RBAC.
//
// -----------------------------------------------------------------------------
// PER-AGENT WORKLOAD IDENTITY MODEL (the heart of the security story)
// -----------------------------------------------------------------------------
//  * orchestrator UAMI (agpoc-id-orchestrator-dev)
//      - bound to Container Apps app `agpoc-aca-orch-dev`
//      - reads secrets (Key Vault Secrets User), calls AOAI (OpenAI User),
//        reads Search (Index Data Reader), reads/writes Cosmos audit (data role),
//        reads synthetic Storage (Blob Data Reader).
//      - acquires Entra tokens (azure-identity DefaultAzureCredential) to call
//        APIM with an access token carrying the orchestrator's app role/scope.
//  * tool-bridge UAMI (agpoc-id-toolbridge-dev)
//      - bound to the Function Apps (tools + durable HITL).
//      - executes tools: reads Search, reads/writes Cosmos, reads secrets,
//        send/listen on Service Bus (assigned in functions.bicep co-located with
//        the queue), reads synthetic Storage.
//  * ui UAMI (agpoc-id-ui-dev)
//      - bound to the UI host (Static Web App / Container App).
//      - NO data-plane Azure roles. The UI only calls the orchestrator's HTTPS
//        ingress; all privileged calls happen server-side.
//
// FEDERATED CREDENTIALS NOTE (GitHub OIDC, no client secrets):
//   CI/CD authenticates to Azure with azure/login + OIDC against a SEPARATE
//   deployer app registration (NOT these runtime UAMIs). Configure a federated
//   identity credential on that app:
//     subject: repo:<org>/<repo>:environment:dev   (or :ref:refs/heads/main)
//     issuer : https://token.actions.githubusercontent.com
//     audience: api://AzureADTokenExchange
//   See .github/workflows/README.md. Runtime UAMIs need NO federated creds —
//   they are consumed directly by ACA/Functions via the `userAssignedIdentities`
//   block (managed identity, not OIDC).
//
// APIM TOKEN VALIDATION NOTE (deterministic zone):
//   APIM (agpoc-apim-dev) is the tool bridge. Its inbound policy validates the
//   caller's Entra JWT (validate-jwt against the tenant), then enforces the
//   required SCOPE/app-role claim per tool (e.g. tools.read, tools.execute).
//   The orchestrator UAMI's token must carry the scope the tool requires, so
//   tool-scope enforcement is data-driven at APIM — NOT prompt-driven. See
//   apim.bicep + infra/apim/policies/inbound-tool-call.xml.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Resource prefix (canonical: agpoc).')
param prefix string

@description('Environment suffix (canonical: dev).')
param env string

// Names of ALREADY-DEPLOYED resources we grant the UAMIs access to.
// These are passed from main.bicep AFTER the resource modules run, so the
// `existing` references below resolve cleanly (no circular dependency).
@description('Key Vault name to grant Secrets User on.')
param keyVaultName string

@description('Cosmos DB account name to grant the data-plane role on.')
param cosmosAccountName string

@description('Azure OpenAI account name to grant OpenAI User on.')
param openAiAccountName string

@description('Azure AI Search service name to grant Index Data Reader on.')
param searchServiceName string

@description('Storage account name to grant Blob Data Reader on.')
param storageAccountName string

// -----------------------------------------------------------------------------
// Built-in role definition IDs (least privilege). Sourced from Azure docs.
// -----------------------------------------------------------------------------
var roleIds = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  cognitiveServicesOpenAiUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  storageBlobDataReader: '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
}
// Cosmos DB uses a SEPARATE data-plane RBAC system (not Azure RBAC). The
// built-in "Cosmos DB Built-in Data Contributor" definition id is fixed:
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

// -----------------------------------------------------------------------------
// User-assigned managed identities (one per agent workload)
// -----------------------------------------------------------------------------
resource idOrchestrator 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-orchestrator-${env}'
  location: location
  tags: tags
}

resource idToolBridge 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-toolbridge-${env}'
  location: location
  tags: tags
}

resource idUi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-ui-${env}'
  location: location
  tags: tags
}

// -----------------------------------------------------------------------------
// Existing-resource references (must already be deployed by main.bicep)
// -----------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: openAiAccountName
}
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchServiceName
}
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' existing = {
  name: cosmosAccountName
}

// =============================================================================
// RBAC — KEY VAULT (Secrets User): orchestrator + tool-bridge read secrets.
// =============================================================================
resource kvOrchestrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, idOrchestrator.id, roleIds.keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
    principalId: idOrchestrator.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource kvToolBridge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, idToolBridge.id, roleIds.keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
    principalId: idToolBridge.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// RBAC — AZURE OPENAI (OpenAI User): orchestrator (+ tool-bridge for tool-side
// model calls) invoke gpt-4o / gpt-4o-mini.
// =============================================================================
resource aoaiOrchestrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, idOrchestrator.id, roleIds.cognitiveServicesOpenAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesOpenAiUser)
    principalId: idOrchestrator.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource aoaiToolBridge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, idToolBridge.id, roleIds.cognitiveServicesOpenAiUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cognitiveServicesOpenAiUser)
    principalId: idToolBridge.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// RBAC — AZURE AI SEARCH (Index Data Reader): read-only retrieval for UC1.
// =============================================================================
resource searchOrchestrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, idOrchestrator.id, roleIds.searchIndexDataReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchIndexDataReader)
    principalId: idOrchestrator.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource searchToolBridge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, idToolBridge.id, roleIds.searchIndexDataReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.searchIndexDataReader)
    principalId: idToolBridge.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// RBAC — STORAGE (Blob Data Reader): read-only on the synthetic data set.
// =============================================================================
resource storageOrchestrator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, idOrchestrator.id, roleIds.storageBlobDataReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataReader)
    principalId: idOrchestrator.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
resource storageToolBridge 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, idToolBridge.id, roleIds.storageBlobDataReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataReader)
    principalId: idToolBridge.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// COSMOS DATA-PLANE RBAC (separate system): orchestrator + tool-bridge write
// audit/state. Uses sqlRoleAssignments, NOT Microsoft.Authorization. Scope is
// the whole account (data-plane scope strings are account-relative).
// =============================================================================
resource cosmosOrchestrator 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, idOrchestrator.id, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: idOrchestrator.properties.principalId
    scope: cosmos.id
  }
}
resource cosmosToolBridge 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = {
  parent: cosmos
  name: guid(cosmos.id, idToolBridge.id, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: idToolBridge.properties.principalId
    scope: cosmos.id
  }
}

// -----------------------------------------------------------------------------
// Outputs — consumed by containerapps.bicep, functions.bicep, ui hosting.
// -----------------------------------------------------------------------------
@description('Orchestrator UAMI resource ID (bind to Container App).')
output orchestratorIdentityId string = idOrchestrator.id
@description('Orchestrator UAMI principal (object) ID.')
output orchestratorPrincipalId string = idOrchestrator.properties.principalId
@description('Orchestrator UAMI client ID (AZURE_CLIENT_ID for DefaultAzureCredential).')
output orchestratorClientId string = idOrchestrator.properties.clientId

@description('Tool-bridge UAMI resource ID (bind to Function Apps).')
output toolBridgeIdentityId string = idToolBridge.id
@description('Tool-bridge UAMI principal (object) ID.')
output toolBridgePrincipalId string = idToolBridge.properties.principalId
@description('Tool-bridge UAMI client ID.')
output toolBridgeClientId string = idToolBridge.properties.clientId

@description('UI UAMI resource ID (bind to UI host).')
output uiIdentityId string = idUi.id
@description('UI UAMI client ID.')
output uiClientId string = idUi.properties.clientId
