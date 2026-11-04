targetScope = 'subscription'

@description('Azure region for the LabForge core resources.')
param location string = 'centralindia'

@description('PostgreSQL administrator login.')
param postgresAdminUsername string

@secure()
@description('Set through LABFORGE_POSTGRES_ADMIN_PASSWORD using the bicepparam file.')
param postgresAdminPassword string

resource coreResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-labforge-core'
  location: location
}

resource labVmsResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-labforge-labvms'
  location: location
}

module core './modules/core.bicep' = {
  name: 'labforge-core'
  scope: coreResourceGroup
  params: {
    location: location
    postgresAdminUsername: postgresAdminUsername
    postgresAdminPassword: postgresAdminPassword
  }
}

module labVmAccess './modules/labvm-access.bicep' = {
  name: 'labforge-labvm-access'
  scope: labVmsResourceGroup
  params: {
    apiPrincipalId: core.outputs.apiPrincipalId
  }
}

output appsSubnetId string = core.outputs.appsSubnetId
output labVmsSubnetId string = core.outputs.labVmsSubnetId
output databaseSubnetId string = core.outputs.databaseSubnetId
output galleryName string = core.outputs.galleryName
output apiIdentityClientId string = core.outputs.apiIdentityClientId
output keyVaultUri string = core.outputs.keyVaultUri
