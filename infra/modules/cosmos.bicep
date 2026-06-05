// =============================================================================
// cosmos.bicep
// Azure Cosmos DB (NoSQL / Core SQL) — audit + state store for the PoC.
//
// Canonical (POC_SPEC.md):
//   Account  -> agpoc-cosmos-dev
//   Database -> agentaudit
//   Containers (partition keys chosen for the agentic audit model):
//     runs      pk /run_id      -> one doc per orchestrator run
//     steps     pk /run_id      -> per-step trace, co-located with its run
//     handoffs  pk /run_id      -> UC2 transaction-handoff objects
//     tokens    pk /run_id      -> per-call token records (canonical contract)
//
// `tokens` is partitioned by /run_id (per spec) so the Token Monitor can read a
// whole run's usage with a single-partition query. Cross-run rollups go through
// App Insights `gen_ai.token.usage` (see observability.bicep + KQL library).
// =============================================================================

@description('Azure region (canonical: southeastasia).')
param location string

@description('Common resource tags.')
param tags object

@description('Cosmos DB account name (canonical: agpoc-cosmos-dev).')
param cosmosAccountName string

@description('SQL database name (canonical: agentaudit).')
param databaseName string = 'agentaudit'

@description('Log Analytics workspace ID for diagnostic settings.')
param logAnalyticsId string

@description('Shared autoscale max RU/s for the database (containers share it). PoC default 1000.')
@minValue(1000)
@maxValue(100000)
param autoscaleMaxThroughput int = 1000

// Canonical container definitions. Partition key for every container is /run_id
// so per-run reads stay single-partition.
var containers = [
  { name: 'runs', partitionKey: '/run_id' }
  { name: 'steps', partitionKey: '/run_id' }
  { name: 'handoffs', partitionKey: '/run_id' }
  { name: 'tokens', partitionKey: '/run_id' }
]

// -----------------------------------------------------------------------------
// Cosmos account (single-region, session consistency — right-sized for a PoC)
// -----------------------------------------------------------------------------
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    disableLocalAuth: false // PoC: key auth allowed. Prod: true (Entra-only).
    enableAutomaticFailover: false
    minimalTlsVersion: 'Tls12'
    capabilities: [] // no serverless; using shared autoscale below.
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Database with shared autoscale throughput (containers inherit the bucket)
// -----------------------------------------------------------------------------
resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: cosmos
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
    options: {
      autoscaleSettings: {
        maxThroughput: autoscaleMaxThroughput
      }
    }
  }
}

// -----------------------------------------------------------------------------
// Containers (runs, steps, handoffs, tokens) — all pk /run_id
// -----------------------------------------------------------------------------
resource cosmosContainers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for c in containers: {
    parent: database
    name: c.name
    properties: {
      resource: {
        id: c.name
        partitionKey: {
          paths: [
            c.partitionKey
          ]
          kind: 'Hash'
          version: 2
        }
        indexingPolicy: {
          indexingMode: 'consistent'
          automatic: true
          includedPaths: [
            {
              path: '/*'
            }
          ]
          excludedPaths: [
            {
              path: '/"_etag"/?'
            }
          ]
        }
        // 365-day TTL default keeps the PoC audit store from growing forever;
        // individual docs can override with their own `ttl`.
        defaultTtl: 31536000
      }
    }
  }
]

// -----------------------------------------------------------------------------
// Diagnostic settings -> Log Analytics
// -----------------------------------------------------------------------------
resource cosmosDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: cosmos
  name: 'to-law'
  properties: {
    workspaceId: logAnalyticsId
    logs: [
      {
        category: 'DataPlaneRequests'
        enabled: true
      }
      {
        category: 'QueryRuntimeStatistics'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Requests'
        enabled: true
      }
    ]
  }
}

@description('Cosmos DB account resource ID.')
output cosmosAccountId string = cosmos.id

@description('Cosmos DB account name (RBAC scope used in identity.bicep).')
output cosmosAccountName string = cosmos.name

@description('Cosmos DB document endpoint (https://agpoc-cosmos-dev.documents.azure.com:443/).')
output cosmosEndpoint string = cosmos.properties.documentEndpoint

@description('Database name.')
output databaseName string = database.name
