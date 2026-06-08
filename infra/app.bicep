// =============================================================================
// app.bicep — application hosting layer for the Agentic AI Platform PoC.
// Scope: resource group (same RG as foundry.bicep).
//
// Provisions the runtime that hosts the orchestrator + UI on top of the AI core
// created by foundry.bicep:
//   * Azure Container Registry (the backend image is built here)
//   * Container Apps managed environment (wired to the foundry Log Analytics)
//   * Orchestrator Container App (FastAPI) — runs under the orchestrator UAMI,
//     pulls from ACR via managed identity, and is fully env-wired to the AI core
//   * Static Web App (the React SPA)
//   * RBAC: AcrPull (UAMI -> ACR) + Azure AI User (UAMI -> Foundry account) so
//     the orchestrator can pull its image and invoke the live Foundry agents.
//
// The deploy script deploys foundry.bicep first, then passes its outputs into
// this module, then builds + pushes the real image and updates the app. The app
// starts on a public quickstart placeholder image so the environment is healthy
// before the first real image exists (chicken-and-egg on first deploy).
// =============================================================================

@description('Deployment region (match the foundry stack region).')
param location string = resourceGroup().location

@description('Resource name prefix.')
param prefix string = 'agpoc'

@description('Environment tag/suffix.')
param env string = 'dev'

@description('Container image for the orchestrator. Defaults to a public placeholder; the deploy script swaps in the ACR image after the first build.')
param orchestratorImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

// ---- Wiring from foundry.bicep outputs --------------------------------------
@description('Resource id of the orchestrator user-assigned managed identity (foundry output: orchestratorIdentityResourceId).')
param orchestratorIdentityResourceId string

@description('Client id of the orchestrator UAMI (foundry output: orchestratorIdentityClientId).')
param orchestratorIdentityClientId string

@description('Principal (object) id of the orchestrator UAMI (foundry output: orchestratorIdentityPrincipalId).')
param orchestratorIdentityPrincipalId string

@description('Foundry account name (foundry output: foundryAccountName) — used as the RBAC scope for Azure AI User.')
param foundryAccountName string

@description('Foundry data-plane project endpoint (foundry output: foundryProjectEndpoint).')
param foundryProjectEndpoint string

@description('Foundry project name (foundry output: projectName).')
param foundryProjectName string

@description('Azure OpenAI endpoint (foundry output: aoaiEndpoint).')
param aoaiEndpoint string

@description('Cosmos DB endpoint (foundry output: cosmosEndpoint).')
param cosmosEndpoint string

@description('Cosmos audit database name.')
param cosmosDatabase string = 'agentaudit'

@description('Key Vault URI (foundry output: keyVaultUri).')
param keyVaultUri string

@description('Application Insights connection string (foundry output: appInsightsConnectionString).')
@secure()
param appInsightsConnectionString string

@description('Log Analytics workspace name created by foundry.bicep (default: <prefix>-law-<env>).')
param logAnalyticsWorkspaceName string = '${prefix}-law-${env}'

@description('Run the orchestrator with mocked tool/data adapters (synthetic-only PoC default).')
param mockMode bool = true

@description('Use live Azure OpenAI / Foundry model calls.')
param liveLlm bool = true

@description('Bind in-code agents to the live Foundry agents/workflows.')
param useFoundryAgents bool = true

@description('Drive UC1/UC2 orchestration with the provisioned Foundry workflow agents (server-side agent workflow incl. the HITL Question node). The Python orchestrator still owns the deterministic policy gates + AWAITING_APPROVAL state machine.')
param useFoundryWorkflows bool = true

@description('Registered credit-memo workflow agent name (provision_foundry_agents.WORKFLOWS).')
param creditMemoWorkflow string = 'credit-memo-workflow'

@description('Registered banking-control workflow agent name (provision_foundry_agents.WORKFLOWS).')
param bankingWorkflow string = 'banking-control-workflow'

var tags = {
  project: 'agentic-ai-poc'
  env: env
  partner: 'DataX-TechX-Microsoft'
  data: 'synthetic-only'
}

var uniq = uniqueString(resourceGroup().id)
var acrName = take(toLower('${prefix}acr${env}${uniq}'), 50)
var acaEnvName = '${prefix}-aca-env-${env}'
var acaAppName = '${prefix}-aca-orch-${env}'
var swaName = '${prefix}-swa-${env}'

var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
var roleAzureAiUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Azure AI User (Foundry data-plane)

// ---- Existing resources (created by foundry.bicep) --------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

// ---- Azure Container Registry -----------------------------------------------
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

// AcrPull for the orchestrator UAMI so the Container App pulls via managed identity.
resource raAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, orchestratorIdentityResourceId, roleAcrPull)
  scope: acr
  properties: {
    principalId: orchestratorIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAcrPull)
  }
}

// Azure AI User for the orchestrator UAMI so it can invoke live Foundry agents.
resource raAzureAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, orchestratorIdentityResourceId, roleAzureAiUser)
  scope: foundry
  properties: {
    principalId: orchestratorIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAiUser)
  }
}

// ---- Container Apps managed environment -------------------------------------
resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: acaEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// ---- Orchestrator Container App (FastAPI) -----------------------------------
resource acaApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: acaAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${orchestratorIdentityResourceId}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [ { latestRevision: true, weight: 100 } ]
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: orchestratorIdentityResourceId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'orchestrator'
          image: orchestratorImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'AZURE_CLIENT_ID', value: orchestratorIdentityClientId }
            { name: 'ENTRA_ORCHESTRATOR_CLIENT_ID', value: orchestratorIdentityClientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'KEY_VAULT_URI', value: keyVaultUri }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'AZURE_OPENAI_ENDPOINT', value: aoaiEndpoint }
            { name: 'AOAI_DEPLOYMENT_GPT4O', value: 'gpt-4o' }
            { name: 'AOAI_DEPLOYMENT_GPT4O_MINI', value: 'gpt-4o-mini' }
            { name: 'TOKEN_METRIC_NAME', value: 'gen_ai.token.usage' }
            { name: 'LIVE_LLM', value: string(liveLlm) }
            { name: 'MOCK_MODE', value: string(mockMode) }
            { name: 'USE_FOUNDRY_AGENTS', value: string(useFoundryAgents) }
            { name: 'USE_FOUNDRY_WORKFLOWS', value: string(useFoundryWorkflows) }
            { name: 'FOUNDRY_CREDIT_MEMO_WORKFLOW', value: creditMemoWorkflow }
            { name: 'FOUNDRY_BANKING_WORKFLOW', value: bankingWorkflow }
            { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
            { name: 'FOUNDRY_PROJECT_NAME', value: foundryProjectName }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
  dependsOn: [ raAcrPull ]
}

// ---- Static Web App (React SPA) ---------------------------------------------
resource swa 'Microsoft.Web/staticSites@2023-12-01' = {
  name: swaName
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard' }
  properties: {
    allowConfigFileUpdates: true
  }
}

// ---- Outputs (consumed by the deploy script) --------------------------------
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output containerAppName string = acaApp.name
output orchestratorFqdn string = acaApp.properties.configuration.ingress.fqdn
output staticWebAppName string = swa.name
output staticWebAppDefaultHostname string = swa.properties.defaultHostname
