// =============================================================================
// swa.bicep — Azure Static Web App resource (Free SKU) for the PoC SPA.
// Tagged azd-service-name: web so `azd deploy` targets it.
// =============================================================================
@description('Name of the Static Web App resource.')
param name string

@description('Location for the Static Web App. Must be an SWA-supported region.')
param location string

@description('Tags to apply to the resource.')
param tags object = {}

@allowed([
  'Free'
  'Standard'
])
@description('SKU/tier for the Static Web App.')
param sku string = 'Free'

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: {
    name: sku
    tier: sku
  }
  properties: {
    buildProperties: {
      appLocation: '/'
      outputLocation: 'dist'
    }
  }
}

output uri string = 'https://${staticWebApp.properties.defaultHostname}'
output name string = staticWebApp.name
