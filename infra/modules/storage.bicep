// =============================================================================
// storage.bicep
// Storage account with ADLS Gen2 (hierarchical namespace) for the PoC.
//
// Canonical (POC_SPEC.md):
//   Account name -> agpocstoragedev   (no dashes: storage accounts are 3-24 lc alnum)
//   Containers   -> synthetic, memos, templates
//
// Holds SYNTHETIC ONLY data (no PII/production). Purview scans this account
// (see purview.bicep) to prove governance + classification on the synthetic set.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Storage account name (canonical: agpocstoragedev). 3-24 lowercase alphanumeric.')
@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Blob containers to create (canonical: synthetic, memos, templates).')
param containerNames array = [
  'synthetic'
  'memos'
  'templates'
]

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// -----------------------------------------------------------------------------
// Storage account — StorageV2 + isHnsEnabled = ADLS Gen2.
// Public network access stays Enabled for the PoC; flip to Disabled + add the
// private endpoint below for production (see PRIVATE LINK NOTE).
// -----------------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS' // PoC; use ZRS/GZRS for production durability.
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true // <-- ADLS Gen2 hierarchical namespace
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true // PoC convenience; prefer false + Entra-only in prod.
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Allow' // PoC. Production: 'Deny' + private endpoint.
      bypass: 'AzureServices'
    }
  }
}

// -----------------------------------------------------------------------------
// Blob service + containers
// -----------------------------------------------------------------------------
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for name in containerNames: {
    parent: blobService
    name: name
    properties: {
      publicAccess: 'None'
    }
  }
]

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource blobDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobService
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'StorageRead'
        enabled: true
      }
      {
        category: 'StorageWrite'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

// -----------------------------------------------------------------------------
// PRIVATE LINK NOTE (production hardening — intentionally NOT deployed in PoC):
//   1. Set networkAcls.defaultAction = 'Deny' and publicNetworkAccess off.
//   2. Create Microsoft.Network/privateEndpoints for groupIds 'blob' and 'dfs'
//      (dfs = ADLS Gen2 data-plane) into the platform VNet subnet.
//   3. Add privateDnsZones privatelink.blob.core.windows.net and
//      privatelink.dfs.core.windows.net + VNet links + a DNS zone group.
//   TODO(copilot): scaffold infra/modules/privateendpoints.bicep when the
//   PoC graduates to a VNet-integrated landing zone.
// -----------------------------------------------------------------------------

@description('Storage account resource ID.')
output storageAccountId string = storage.id

@description('Storage account name (for Entra RBAC scope in identity.bicep).')
output storageAccountName string = storage.name

@description('Primary blob endpoint.')
output blobEndpoint string = storage.properties.primaryEndpoints.blob

@description('Primary ADLS Gen2 (dfs) endpoint.')
output dfsEndpoint string = storage.properties.primaryEndpoints.dfs
