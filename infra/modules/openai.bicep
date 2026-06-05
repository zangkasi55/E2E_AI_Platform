// =============================================================================
// openai.bicep
// Azure OpenAI (Azure AI Foundry Models) account + model deployments.
//
// Canonical (POC_SPEC.md):
//   Account     -> agpoc-aoai-dev
//   Deployments -> gpt-4o, gpt-4o-mini
//   Region      -> southeastasia (Thailand-nearest serving)
//
// The orchestrator + sub-agents call these via Entra (managed identity, role
// "Cognitive Services OpenAI User" — assigned in identity.bicep). Every call
// emits the canonical token record -> Cosmos `tokens` + `gen_ai.token.usage`.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Azure OpenAI account name (canonical: agpoc-aoai-dev).')
param openAiAccountName string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// Model deployments. capacity is in thousands-of-tokens-per-minute (TPM) units
// for Standard SKUs. Confirm regional quota for southeastasia before deploy
// (see docs/deployment-plan.md Prerequisites).
@description('Model deployment definitions (name, model, version, capacity).')
param deployments array = [
  {
    name: 'gpt-4o'
    model: 'gpt-4o'
    version: '2024-11-20'
    skuName: 'Standard'
    capacity: 20 // 20K TPM — PoC budget; raise per quota.
  }
  {
    name: 'gpt-4o-mini'
    model: 'gpt-4.1-mini'
    version: '2025-04-14'
    skuName: 'Standard'
    capacity: 50 // cheaper, higher TPM for sub-agent / slot-filling traffic.
  }
]

// -----------------------------------------------------------------------------
// Azure OpenAI account (kind 'OpenAI'). customSubDomainName is REQUIRED for
// Entra token auth + the standard https://<name>.openai.azure.com endpoint.
// -----------------------------------------------------------------------------
resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openAiAccountName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAiAccountName
    publicNetworkAccess: 'Enabled' // PoC. Prod: private endpoint + Disabled.
    disableLocalAuth: false // PoC allows key fallback; Entra is preferred path.
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

// -----------------------------------------------------------------------------
// Model deployments. @batchSize(1) forces SEQUENTIAL creation — Azure OpenAI
// rejects parallel deployment creation on one account.
//
// CONTENT FILTER NOTE: each deployment inherits the account's default content
// filter (Microsoft.Default — hate/sexual/violence/self-harm at medium). For
// financial-services you typically attach a custom RAI policy via
// Microsoft.CognitiveServices/accounts/raiPolicies and set
// `raiPolicyName` below. TODO(operator): create the FSI RAI policy in Foundry,
// then set raiPolicyName: 'agpoc-fsi-strict' here and redeploy.
// -----------------------------------------------------------------------------
@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = [
  for d in deployments: {
    parent: openAi
    name: d.name
    sku: {
      name: d.skuName
      capacity: d.capacity
    }
    properties: {
      model: {
        format: 'OpenAI'
        name: d.model
        version: d.version
      }
      versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
      // raiPolicyName: 'agpoc-fsi-strict' // TODO(operator): attach FSI content filter.
    }
  }
]

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics (audit + RAI/content-filter events)
// -----------------------------------------------------------------------------
resource aoaiDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: openAi
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'Audit'
        enabled: true
      }
      {
        category: 'RequestResponse'
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

@description('Azure OpenAI account resource ID.')
output openAiAccountId string = openAi.id

@description('Azure OpenAI account name (RBAC scope used in identity.bicep).')
output openAiAccountName string = openAi.name

@description('Azure OpenAI endpoint (https://agpoc-aoai-dev.openai.azure.com/).')
output openAiEndpoint string = openAi.properties.endpoint

@description('Deployment names for app configuration.')
output deploymentNames array = [for (d, i) in deployments: d.name]
