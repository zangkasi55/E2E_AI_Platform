// =============================================================================
// purview.bicep
// Microsoft Purview account — DATA GOVERNANCE for the PoC.
//
// Canonical name (POC_SPEC.md): agpoc-purview-dev
//
// -----------------------------------------------------------------------------
// WHAT PURVIEW DOES IN THIS PoC (data-plane work is post-deploy; see plan)
// -----------------------------------------------------------------------------
//  * DATA MAP: register the storage account `agpocstoragedev` (containers
//    synthetic / memos / templates) as a data source in the Purview data map.
//  * CLASSIFICATIONS: run a scan that applies built-in + custom classifications
//    (e.g. National ID, Phone Number, Account Number) over the SYNTHETIC data.
//    Even though the PoC uses synthetic-only data, the scan PROVES the control:
//    it shows what WOULD be flagged as PII on real data, and feeds the APIM
//    field-level redaction list (inbound-tool-call.xml).
//  * PII SCANNING: scheduled/on-demand scan of the ADLS Gen2 + blob containers;
//    results published to the catalog with sensitivity labels.
//  * APPROVED SOURCES GOVERNANCE: the catalog is the source of truth for which
//    data sources the `doc_retrieval` agent is allowed to use. Tools only query
//    sources registered + classified here — governance gates retrieval.
//
// Purview's MANAGED IDENTITY (system-assigned, below) must be granted
// "Storage Blob Data Reader" on `agpocstoragedev` so the scanner can read the
// synthetic data. That role assignment is created here (co-located with Purview)
// rather than in identity.bicep, because it is Purview-specific plumbing.
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Purview account name (canonical: agpoc-purview-dev).')
param purviewAccountName string

@description('Reuse an existing Purview account instead of creating a new one.')
param useExistingPurview bool = false

@description('Resource group that contains the existing Purview account when useExistingPurview=true.')
param existingPurviewResourceGroupName string = ''

@description('Storage account name Purview scans (canonical: agpocstoragedev).')
param storageAccountName string

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

// -----------------------------------------------------------------------------
// Purview account (system-assigned identity used by the scanner).
// -----------------------------------------------------------------------------
resource purview 'Microsoft.Purview/accounts@2021-12-01' = if (!useExistingPurview) {
  name: purviewAccountName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    publicNetworkAccess: 'Enabled' // PoC. Prod: private endpoints (portal/ingestion).
    managedResourceGroupName: '${purviewAccountName}-managed'
  }
}

resource purviewExisting 'Microsoft.Purview/accounts@2021-12-01' existing = if (useExistingPurview) {
  scope: resourceGroup(existingPurviewResourceGroupName)
  name: purviewAccountName
}

var purviewResourceId = useExistingPurview ? purviewExisting!.id : purview!.id
var purviewPrincipalId = useExistingPurview ? purviewExisting!.identity.principalId : purview!.identity.principalId
var purviewCatalogEndpoint = useExistingPurview ? purviewExisting!.properties.endpoints.catalog : purview!.properties.endpoints.catalog

// -----------------------------------------------------------------------------
// Grant Purview's scanner identity read access to the synthetic storage so it
// can run the PII classification scan.
// -----------------------------------------------------------------------------
var storageBlobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource purviewStorageReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, purviewResourceId, storageBlobDataReaderRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleId)
    principalId: purviewPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource purviewDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!useExistingPurview) {
  scope: purview
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'ScanStatusLogEvent'
        enabled: true
      }
      {
        category: 'DataSensitivityLogEvent'
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

// NOTE: diagnostics for an existing Purview account in a different RG must be
// managed in that RG/subscription context.

@description('Purview account resource ID.')
output purviewAccountId string = purviewResourceId

@description('Purview account name.')
output purviewAccountName string = purviewAccountName

@description('Purview atlas/catalog endpoint.')
output purviewCatalogEndpoint string = purviewCatalogEndpoint

@description('Purview Studio URL for browser access.')
output purviewStudioUrl string = 'https://web.purview.azure.com/resource${purviewResourceId}'
