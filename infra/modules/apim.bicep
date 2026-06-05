// =============================================================================
// apim.bicep
// Azure API Management — the MCP / AGENT TOOL BRIDGE for the PoC.
//
// Canonical name (POC_SPEC.md): agpoc-apim-dev
//
// APIM is the DETERMINISTIC CONTROL PLANE between agents and tools. Every tool
// call (search_documents, get_financials, ..., request_transaction_handoff)
// goes through APIM, which enforces — by CONFIGURATION, not prompt:
//   (a) JWT / Entra token validation
//   (b) per-call scope check (tool-scope / PDP)
//   (c) field-level PII filtering (redaction)
//   (d) logging to Application Insights
//   (e) rate limiting
// The full inbound policy XML lives in infra/apim/policies/inbound-tool-call.xml
// and is loaded below via loadTextContent().
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('APIM service name (canonical: agpoc-apim-dev).')
param apimName string

@description('Publisher email for APIM notifications.')
param publisherEmail string = 'datax-techx@example.com'

@description('Publisher organisation name.')
param publisherName string = 'DataX / TechX (SCBX)'

@description('Entra tenant ID (used by the validate-jwt named value).')
param tenantId string = subscription().tenantId

@description('Tool-bridge App ID URI / audience (api://agpoc-tool-bridge).')
param toolBridgeAudience string = 'api://agpoc-tool-bridge'

@description('Default required scope when an operation does not override it.')
param defaultRequiredScope string = 'tools.execute'

@description('Backend base URL of the Functions tool host.')
param toolsBackendUrl string

@description('Application Insights resource ID for APIM logging.')
param appInsightsId string

@description('Application Insights instrumentation key for the APIM logger.')
param appInsightsInstrumentationKey string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// -----------------------------------------------------------------------------
// APIM service. Developer SKU = cheapest tier that supports policy + VNet later;
// fine for a PoC (no SLA). Use Standard/Premium for production.
// -----------------------------------------------------------------------------
resource apim 'Microsoft.ApiManagement/service@2023-05-01-preview' = {
  name: apimName
  location: location
  tags: tags
  sku: {
    name: 'Developer'
    capacity: 1
  }
  identity: {
    type: 'SystemAssigned' // APIM uses this to read AOAI/Key Vault if needed.
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

// -----------------------------------------------------------------------------
// Named values consumed by the inbound policy (see inbound-tool-call.xml).
// -----------------------------------------------------------------------------
resource nvTenantId 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'tenant-id'
  properties: {
    displayName: 'tenant-id'
    value: tenantId
  }
}
resource nvAudience 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'tool-bridge-audience'
  properties: {
    displayName: 'tool-bridge-audience'
    value: toolBridgeAudience
  }
}
resource nvScope 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'required-scope'
  properties: {
    displayName: 'required-scope'
    value: defaultRequiredScope
  }
}
resource nvBackend 'Microsoft.ApiManagement/service/namedValues@2023-05-01-preview' = {
  parent: apim
  name: 'tools-backend-url'
  properties: {
    displayName: 'tools-backend-url'
    value: toolsBackendUrl
  }
}

// -----------------------------------------------------------------------------
// Application Insights logger + diagnostics (control (d) logging).
// -----------------------------------------------------------------------------
resource apimLogger 'Microsoft.ApiManagement/service/loggers@2023-05-01-preview' = {
  parent: apim
  name: 'appinsights'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appInsightsId
    credentials: {
      instrumentationKey: appInsightsInstrumentationKey
    }
  }
}

// -----------------------------------------------------------------------------
// The TOOL CATALOG API. The OpenAPI for the 9 canonical tools is imported at the
// data plane (see deployment-plan.md / functions.yml). Here we declare the API
// shell + attach the inbound policy so the controls exist from first deploy.
// -----------------------------------------------------------------------------
resource toolApi 'Microsoft.ApiManagement/service/apis@2023-05-01-preview' = {
  parent: apim
  name: 'agent-tools'
  properties: {
    displayName: 'Agent Tool Catalog'
    description: 'MCP-style tool bridge for the agentic platform (UC1 + UC2 tools).'
    path: 'tools'
    protocols: [
      'https'
    ]
    subscriptionRequired: true
    serviceUrl: toolsBackendUrl
    // TODO(copilot): import the full OpenAPI (9 tools) via `format: openapi` +
    // `value: loadTextContent('../apim/openapi/tools.json')` once the Functions
    // contract is finalized. For now the API is policy-governed and proxies all.
  }
}

// API-scoped inbound policy = the deterministic control plane. Loaded from XML.
resource toolApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2023-05-01-preview' = {
  parent: toolApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('../apim/policies/inbound-tool-call.xml')
  }
}

// Per-API diagnostics -> App Insights (sampling at 100% for the PoC demo).
resource apiDiagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2023-05-01-preview' = {
  parent: toolApi
  name: 'applicationinsights'
  properties: {
    loggerId: apimLogger.id
    alwaysLog: 'allErrors'
    sampling: {
      samplingType: 'fixed'
      percentage: 100
    }
    verbosity: 'information'
  }
}

// -----------------------------------------------------------------------------
// Product + subscription. The orchestrator subscribes to call tools; the
// subscription key is stored as the `apim-subscription-key` Key Vault secret.
// -----------------------------------------------------------------------------
resource toolProduct 'Microsoft.ApiManagement/service/products@2023-05-01-preview' = {
  parent: apim
  name: 'agent-tools-product'
  properties: {
    displayName: 'Agent Tools'
    description: 'Subscription product fronting the agent tool catalog.'
    subscriptionRequired: true
    approvalRequired: false
    state: 'published'
  }
}

resource productApiLink 'Microsoft.ApiManagement/service/products/apiLinks@2023-05-01-preview' = {
  parent: toolProduct
  name: 'agent-tools-link'
  properties: {
    apiId: toolApi.id
  }
}

resource orchestratorSubscription 'Microsoft.ApiManagement/service/subscriptions@2023-05-01-preview' = {
  parent: apim
  name: 'orchestrator-sub'
  properties: {
    displayName: 'Orchestrator tool subscription'
    scope: toolProduct.id
    state: 'active'
  }
}

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource apimDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: apim
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'GatewayLogs'
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

@description('APIM service resource ID.')
output apimId string = apim.id

@description('APIM service name.')
output apimName string = apim.name

@description('APIM gateway URL (https://agpoc-apim-dev.azure-api.net).')
output apimGatewayUrl string = apim.properties.gatewayUrl

@description('Tool catalog API path (gateway/<path>).')
output toolApiPath string = toolApi.properties.path
