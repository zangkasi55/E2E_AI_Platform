// =============================================================================
// defender.bicep
// Microsoft Defender for Cloud — security posture plans for the PoC.
//
// Canonical (POC_SPEC.md): Defender for Cloud (subscription plan).
//
// IMPORTANT — SCOPE: Defender plans (Microsoft.Security/pricings) are
// SUBSCRIPTION-SCOPED, not resource-group-scoped. This module therefore sets
//   targetScope = 'subscription'
// and is invoked from main.bicep WITHOUT a `scope: rg` (it applies to the whole
// subscription). Enabling a plan affects every resource of that type in the sub,
// so confirm with the subscription owner before running in a shared tenant.
//
// PoC stance: enable the FREE foundational CSPM everywhere, and turn on the
// paid plans that matter for an agentic data app — Key Vault, Storage, and the
// (AI / OpenAI) plan — at the Standard tier. Toggle via parameters to control
// cost. Cloud Security Posture Management 'Standard' adds agentless scanning +
// attack-path analysis; leave 'Free' for a zero-cost PoC.
// =============================================================================

targetScope = 'subscription'

@description('Enable Standard CSPM (paid: attack paths, agentless scan). PoC default false = Free CSPM.')
param enableStandardCspm bool = false

@description('Enable Defender for Key Vault (recommended for a secrets-heavy app).')
param enableKeyVaultPlan bool = true

@description('Enable Defender for Storage (malware + sensitive-data threat detection).')
param enableStoragePlan bool = true

@description('Enable Defender for AI / Azure OpenAI workloads (prompt-injection, anomalous use).')
param enableAiPlan bool = true

// -----------------------------------------------------------------------------
// CSPM — foundational posture management.
// -----------------------------------------------------------------------------
resource cspm 'Microsoft.Security/pricings@2024-01-01' = {
  name: 'CloudPosture'
  properties: {
    pricingTier: enableStandardCspm ? 'Standard' : 'Free'
  }
}

// -----------------------------------------------------------------------------
// Defender for Key Vault.
// -----------------------------------------------------------------------------
resource keyVaultPlan 'Microsoft.Security/pricings@2024-01-01' = if (enableKeyVaultPlan) {
  name: 'KeyVaults'
  properties: {
    pricingTier: 'Standard'
    subPlan: 'PerKeyVault'
  }
}

// -----------------------------------------------------------------------------
// Defender for Storage (malware scanning + sensitive data threat detection,
// which complements the Purview classification of the synthetic data).
// -----------------------------------------------------------------------------
resource storagePlan 'Microsoft.Security/pricings@2024-01-01' = if (enableStoragePlan) {
  name: 'StorageAccounts'
  properties: {
    pricingTier: 'Standard'
    subPlan: 'DefenderForStorageV2'
  }
}

// -----------------------------------------------------------------------------
// Defender for AI workloads — threat protection for Azure OpenAI usage
// (prompt-injection alerts, credential exfiltration, anomalous model calls).
// Plan name 'AI' as of the 2024-01-01 API.
// -----------------------------------------------------------------------------
resource aiPlan 'Microsoft.Security/pricings@2024-01-01' = if (enableAiPlan) {
  name: 'AI'
  properties: {
    pricingTier: 'Standard'
  }
}

@description('CSPM tier applied.')
output cspmTier string = cspm.properties.pricingTier
