// =============================================================================
// observability.bicep
// Log Analytics workspace + Application Insights for the Agentic AI Platform PoC.
//
// Canonical names (POC_SPEC.md):
//   Log Analytics    -> agpoc-law-dev
//   App Insights     -> agpoc-appi-dev
//
// This module is the OBSERVABILITY BACKBONE. Every other component sends:
//   - resource/diagnostic logs  -> Log Analytics
//   - traces + custom metrics   -> Application Insights (workspace-based)
//
// Token monitoring contract (POC_SPEC.md):
//   Each model call emits the custom metric `gen_ai.token.usage` plus a trace,
//   and a row in Cosmos `tokens`. The saved KQL in infra/observability/kql/
//   token_usage.kql aggregates tokens by agent / model / run / est. cost.
// =============================================================================

@description('Azure region for all resources (canonical: southeastasia).')
param location string

@description('Common resource tags applied to every resource.')
param tags object

@description('Log Analytics workspace name (canonical: agpoc-law-dev).')
param logAnalyticsName string

@description('Application Insights name (canonical: agpoc-appi-dev).')
param appInsightsName string

@description('Log Analytics data retention in days (PoC default 30).')
@minValue(30)
@maxValue(730)
param retentionInDays int = 30

// -----------------------------------------------------------------------------
// Log Analytics workspace (PerGB2018 = pay-as-you-go, fine for a PoC)
// -----------------------------------------------------------------------------
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    workspaceCapping: {
      // PoC cost guard: cap daily ingestion. Raise/remove for load tests.
      dailyQuotaGb: 5
    }
  }
}

// -----------------------------------------------------------------------------
// Application Insights (workspace-based — required for custom metrics + KQL)
// The orchestrator + Functions push OpenTelemetry via the connection string.
// -----------------------------------------------------------------------------
resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// -----------------------------------------------------------------------------
// Saved KQL query: token usage by agent/model.
// NOTE: the full query library lives in infra/observability/kql/token_usage.kql.
// This savedSearch makes the headline query discoverable in the portal.
// The custom metric is named `gen_ai.token.usage`; per-call records also land
// as customEvents named 'gen_ai.token.usage' carrying the canonical fields
// (run_id, agent, step, model, prompt_tokens, completion_tokens, total_tokens,
//  est_cost_usd, use_case).
// -----------------------------------------------------------------------------
resource tokenUsageSavedSearch 'Microsoft.OperationalInsights/workspaces/savedSearches@2020-08-01' = {
  parent: law
  name: 'gen_ai-token-usage-by-agent'
  properties: {
    category: 'Agentic AI PoC'
    displayName: 'Token usage by agent (gen_ai.token.usage)'
    version: 2
    query: '''
customEvents
| where name == "gen_ai.token.usage"
| extend agent = tostring(customDimensions["agent"]),
         model = tostring(customDimensions["model"]),
         total_tokens = toint(customDimensions["total_tokens"]),
         est_cost_usd = todouble(customDimensions["est_cost_usd"])
| summarize total_tokens = sum(total_tokens), est_cost_usd = round(sum(est_cost_usd), 4)
        by agent, model
| order by total_tokens desc
'''
  }
}

// -----------------------------------------------------------------------------
// Outputs (wired into other modules + the orchestrator/Functions app settings)
// -----------------------------------------------------------------------------
@description('Log Analytics workspace resource ID (used for diagnostic settings).')
output logAnalyticsId string = law.id

@description('Log Analytics customer (workspace) ID.')
output logAnalyticsCustomerId string = law.properties.customerId

@description('Application Insights resource ID.')
output appInsightsId string = appInsights.id

@description('Application Insights connection string (preferred over iKey).')
output appInsightsConnectionString string = appInsights.properties.ConnectionString

@description('Application Insights instrumentation key (legacy SDKs).')
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey

@description('Canonical custom metric name emitted per model call.')
output tokenUsageMetricName string = 'gen_ai.token.usage'
