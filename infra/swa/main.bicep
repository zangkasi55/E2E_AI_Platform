// =============================================================================
// main.bicep — subscription-scoped entry point for azd. Creates a resource
// group and an Azure Static Web App (Free) hosting the PoC SPA.
// =============================================================================
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the azd environment; used to derive resource names.')
param environmentName string

@minLength(1)
@description('Primary location for the Static Web App. Must be an SWA-supported region (e.g. eastasia, westeurope, eastus2, westus2, centralus).')
param location string

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module swa 'swa.bicep' = {
  name: 'swa'
  scope: rg
  params: {
    name: 'swa-${resourceToken}'
    location: location
    tags: tags
  }
}

output AZURE_LOCATION string = location
output WEB_URI string = swa.outputs.uri
output WEB_NAME string = swa.outputs.name
