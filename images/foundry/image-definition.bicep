targetScope = 'resourceGroup'

@description('Name of the existing Compute Gallery.')
param galleryName string = 'galLabForge'

@description('Name of the Foundry Windows image definition.')
param imageDefinitionName string = 'img-foundry'

resource gallery 'Microsoft.Compute/galleries@2022-03-03' existing = {
  name: galleryName
}

resource imageDefinition 'Microsoft.Compute/galleries/images@2022-03-03' = {
  parent: gallery
  name: imageDefinitionName
  location: resourceGroup().location
  properties: {
    osType: 'Windows'
    osState: 'Generalized'
    hyperVGeneration: 'V2'
    identifier: {
      publisher: 'LabForge'
      offer: 'Foundry'
      sku: 'windows-2022'
    }
  }
}

output imageDefinitionId string = imageDefinition.id
