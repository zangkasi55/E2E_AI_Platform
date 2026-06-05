// =============================================================================
// keyvault.bicep
// Azure Key Vault for the PoC. Holds secrets the orchestrator / Functions read
// via Key Vault references (App Settings) and azure-identity at runtime.
//
// Canonical name (POC_SPEC.md): agpoc-kv-dev
//
// AUTHZ MODEL: Azure RBAC (enableRbacAuthorization = true). The actual
// "Key Vault Secrets User" role assignments for the per-agent user-assigned
// identities live in identity.bicep (single place for least-privilege RBAC).
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Key Vault name (canonical: agpoc-kv-dev). 3-24 chars.')
@minLength(3)
@maxLength(24)
param keyVaultName string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

@description('Secret placeholders to create. Real values are set post-deploy by an operator or a pipeline secret task — NEVER commit real secrets.')
param secretPlaceholders array = [
  // name = canonical secret name read by the app; value = placeholder.
  // TODO(operator): replace placeholders with real values after deploy
  // (e.g. via: az keyvault secret set ...). Keep these names stable — the
  // orchestrator/Functions reference them by exact name.
  'aoai-api-key' // optional fallback; Entra (managed identity) is preferred.
  'search-admin-key' // optional; prefer RBAC data-plane access.
  'cosmos-connection-string' // optional; prefer Entra + DefaultAzureCredential.
  'servicebus-connection-string'
  'apim-subscription-key' // tool-bridge product subscription key.
]

// -----------------------------------------------------------------------------
// Key Vault
// -----------------------------------------------------------------------------
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true // RBAC, not access policies (see identity.bicep).
    enableSoftDelete: true
    softDeleteRetentionInDays: 7 // PoC minimum; production default is 90.
    enablePurgeProtection: true // required once soft-delete is on for many SKUs.
    publicNetworkAccess: 'Enabled' // PoC. Production: private endpoint + Disabled.
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// -----------------------------------------------------------------------------
// Secret placeholders (empty/sentinel values). Created so App Settings Key Vault
// references resolve immediately; operators overwrite values post-deploy.
// -----------------------------------------------------------------------------
resource secrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [
  for name in secretPlaceholders: {
    parent: keyVault
    name: name
    properties: {
      value: 'REPLACE_ME' // sentinel — overwrite post-deploy. Never commit real secrets.
      contentType: 'placeholder'
    }
  }
]

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics (audit every secret access)
// -----------------------------------------------------------------------------
resource kvDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: keyVault
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'AuditEvent'
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

@description('Key Vault resource ID.')
output keyVaultId string = keyVault.id

@description('Key Vault name (RBAC scope used in identity.bicep).')
output keyVaultName string = keyVault.name

@description('Key Vault URI (https://agpoc-kv-dev.vault.azure.net/).')
output keyVaultUri string = keyVault.properties.vaultUri
