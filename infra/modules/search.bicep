// =============================================================================
// search.bicep
// Azure AI Search — retrieval backend for UC1 (doc_retrieval / search_documents).
//
// Canonical name (POC_SPEC.md): agpoc-search-dev
//
// The `doc_retrieval` sub-agent queries this via the `search_documents` tool
// (APIM-fronted). Data-plane access uses Entra (managed identity) with role
// "Search Index Data Reader" — assigned in identity.bicep.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Azure AI Search service name (canonical: agpoc-search-dev).')
param searchServiceName string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

@description('Search SKU. PoC default "basic" (supports semantic ranker on Standard+).')
@allowed([
  'basic'
  'standard'
  'standard2'
])
param skuName string = 'basic'

// -----------------------------------------------------------------------------
// Search service. authOptions + aadOrApiKey enables BOTH Entra RBAC (preferred)
// and admin-key fallback during PoC bring-up.
// -----------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchServiceName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  identity: {
    type: 'SystemAssigned' // lets Search pull from Storage/AOAI for skillsets later.
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled' // PoC. Prod: 'disabled' + private endpoint.
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    semanticSearch: 'free' // semantic ranker (free tier) — handy for UC1 RAG.
  }
}

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource searchDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: search
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'OperationLogs'
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

// -----------------------------------------------------------------------------
// INDEX NOTE: indexes/indexers/skillsets are created at the data plane
// (REST/SDK), not in Bicep. The PoC `synthetic` blob container is the source.
// TODO(copilot): add a backend/scripts/create_search_index.py that builds the
// `credit-docs` index + indexer from the synthetic memos.
// -----------------------------------------------------------------------------

@description('Azure AI Search service resource ID.')
output searchServiceId string = search.id

@description('Search service name (RBAC scope used in identity.bicep).')
output searchServiceName string = search.name

@description('Search endpoint (https://agpoc-search-dev.search.windows.net).')
output searchEndpoint string = 'https://${search.name}.search.windows.net'
