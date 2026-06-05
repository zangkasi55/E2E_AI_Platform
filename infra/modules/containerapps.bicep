// =============================================================================
// containerapps.bicep
// Container Apps environment + the FastAPI ORCHESTRATOR runtime.
//
// Canonical (POC_SPEC.md): orchestration runtime -> agpoc-aca-orch-dev
//
// The orchestrator (Semantic Kernel) plans the agent graph, calls tools via
// APIM, writes audit/state to Cosmos, emits `gen_ai.token.usage` to App
// Insights, and exposes an HTTPS API the UI consumes. It runs under the
// orchestrator UAMI (Entra access to AOAI/Search/Cosmos/Key Vault).
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Resource prefix (canonical: agpoc).')
param prefix string

@description('Environment suffix (canonical: dev).')
param env string

@description('Orchestrator Container App name (canonical: agpoc-aca-orch-dev).')
param orchestratorAppName string

@description('Orchestrator user-assigned identity resource ID (from identity.bicep).')
param orchestratorIdentityId string

@description('Orchestrator user-assigned identity client ID (DefaultAzureCredential).')
param orchestratorClientId string

@description('Container image. Placeholder until backend.yml pushes the real tag.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('App Insights connection string.')
param appInsightsConnectionString string

@description('Log Analytics workspace name (ACA env reads customerId + shared key from it).')
param logAnalyticsName string

@description('Key Vault URI.')
param keyVaultUri string

@description('Cosmos DB endpoint.')
param cosmosEndpoint string

@description('Cosmos DB database name.')
param cosmosDatabaseName string

@description('Azure OpenAI endpoint.')
param openAiEndpoint string

@description('gpt-4o deployment name.')
param gpt4oDeployment string = 'gpt-4o'

@description('gpt-4o-mini deployment name.')
param gpt4oMiniDeployment string = 'gpt-4o-mini'

@description('Azure AI Search endpoint.')
param searchEndpoint string

@description('APIM gateway URL (tool bridge base).')
param apimGatewayUrl string

@description('APIM tool API path.')
param toolApiPath string

// Existing Log Analytics workspace — read customerId + shared key here so no
// secret has to travel through module outputs.
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

// -----------------------------------------------------------------------------
// Container Apps managed environment, wired to Log Analytics.
// -----------------------------------------------------------------------------
resource acaEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-aca-env-${env}'
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

// -----------------------------------------------------------------------------
// Orchestrator Container App. External ingress on 8000 (FastAPI/uvicorn).
// Identity = orchestrator UAMI. Endpoints passed as env; secrets via Key Vault.
// -----------------------------------------------------------------------------
resource orchestrator 'Microsoft.App/containerApps@2024-03-01' = {
  name: orchestratorAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${orchestratorIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true // UI calls this. Restrict via APIM/Front Door in prod.
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        corsPolicy: {
          // PoC: allow the UI origin. TODO(operator): pin to the SWA URL.
          allowedOrigins: [
            '*'
          ]
          allowedMethods: [
            'GET'
            'POST'
            'OPTIONS'
          ]
        }
      }
    }
    template: {
      containers: [
        {
          name: 'orchestrator'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID' // selects the orchestrator UAMI
              value: orchestratorClientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
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
              name: 'AOAI_DEPLOYMENT_GPT4O'
              value: gpt4oDeployment
            }
            {
              name: 'AOAI_DEPLOYMENT_GPT4O_MINI'
              value: gpt4oMiniDeployment
            }
            {
              name: 'SEARCH_ENDPOINT'
              value: searchEndpoint
            }
            {
              // Tool bridge base the orchestrator calls (with an Entra token).
              name: 'TOOL_BRIDGE_URL'
              value: '${apimGatewayUrl}/${toolApiPath}'
            }
            {
              name: 'TOKEN_METRIC_NAME'
              value: 'gen_ai.token.usage'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1 // keep one warm for the demo
        maxReplicas: 3
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

@description('Orchestrator Container App resource ID.')
output orchestratorAppId string = orchestrator.id

@description('Orchestrator public FQDN (UI base URL + APIM never proxies this).')
output orchestratorFqdn string = orchestrator.properties.configuration.ingress.fqdn

@description('Container Apps environment ID (reused if the UI deploys here too).')
output acaEnvironmentId string = acaEnv.id
