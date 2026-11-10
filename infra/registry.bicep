targetScope = 'resourceGroup'

@minLength(5)
@maxLength(50)
@description('Globally unique Azure Container Registry name. Use lowercase letters and numbers only.')
param registryName string

@minLength(36)
@maxLength(36)
@description('Object ID of the staging GitHub Actions service principal.')
param publisherPrincipalId string

param location string = resourceGroup().location

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource publisherRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, publisherPrincipalId, 'AcrPush')
  scope: registry
  properties: {
    principalId: publisherPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8311e382-0749-4cb8-b61a-304f252e45ec')
  }
}

output registryName string = registry.name
output loginServer string = registry.properties.loginServer
