// =============================================================================
// servicebus.bicep
// Azure Service Bus — eventing backbone for the HITL (human-in-the-loop) flow.
//
// Canonical (POC_SPEC.md):
//   Namespace -> agpoc-sb-dev
//   Queue     -> hitl-approvals
//
// UC1 flow: the Durable Functions orchestrator (agpoc-func-durable-dev) parks an
// approval request on `hitl-approvals`; the Teams reviewer's approve/edit posts
// back, resuming the durable orchestration. "Agent drafts, human decides."
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Service Bus namespace name (canonical: agpoc-sb-dev).')
param serviceBusNamespaceName string

@description('HITL approvals queue name (canonical: hitl-approvals).')
param queueName string = 'hitl-approvals'

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// -----------------------------------------------------------------------------
// Namespace (Standard SKU — required for topics/sessions; PoC uses one queue).
// SystemAssigned identity lets consumers use Entra "Service Bus Data *" roles.
// -----------------------------------------------------------------------------
resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: serviceBusNamespaceName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled' // PoC. Prod: private endpoint + Disabled.
    disableLocalAuth: false // PoC allows SAS; prefer Entra in prod.
  }
}

// -----------------------------------------------------------------------------
// HITL approvals queue. Sessions enabled so a run's approval correlates back to
// the exact paused durable orchestration instance (sessionId = run_id).
// -----------------------------------------------------------------------------
resource hitlQueue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBus
  name: queueName
  properties: {
    requiresSession: true // correlate approval -> paused orchestration by run_id.
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    defaultMessageTimeToLive: 'P1D' // approvals expire after 24h in the PoC.
    deadLetteringOnMessageExpiration: true
  }
}

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource sbDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: serviceBus
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'OperationalLogs'
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

@description('Service Bus namespace resource ID.')
output serviceBusNamespaceId string = serviceBus.id

@description('Service Bus namespace name.')
output serviceBusNamespaceName string = serviceBus.name

@description('Fully-qualified namespace (agpoc-sb-dev.servicebus.windows.net) for Entra clients.')
output serviceBusFqdn string = '${serviceBus.name}.servicebus.windows.net'

@description('HITL queue name.')
output queueName string = hitlQueue.name
