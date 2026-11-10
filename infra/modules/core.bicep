targetScope = 'resourceGroup'

param location string
param postgresAdminUsername string
@secure()
param postgresAdminPassword string
param postgresSkuName string = 'Standard_B1ms'
param postgresSkuTier string = 'Burstable'
param postgresStorageSizeGB int = 32
param logAnalyticsDailyQuotaGb int = 1
param postgresSchedulerPrincipalId string

var vnetName = 'vnet-labforge'
var appsSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-apps')
var databaseSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-db')
var labVmsSubnetId = resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-labvms')
var keyVaultName = 'kv-lf-${uniqueString(resourceGroup().id)}'
var galleryName = 'galLabForge'
var identityName = 'id-labforge-api'
var postgresqlDnsZoneName = 'labforge.postgres.database.azure.com'

resource labNsg 'Microsoft.Network/networkSecurityGroups@2023-09-01' = {
  name: 'nsg-labforge-labvms'
  location: location
  properties: {
    securityRules: [
      {
        name: 'AllowRdpFromAppsSubnet'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '3389'
          sourceAddressPrefix: '10.50.1.0/24'
          destinationAddressPrefix: '10.50.16.0/20'
        }
      }
      {
        name: 'DenyOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.50.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'snet-apps'
        properties: {
          addressPrefix: '10.50.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          delegations: [
            {
              name: 'containerApps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'snet-db'
        properties: {
          addressPrefix: '10.50.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
          delegations: [
            {
              name: 'postgresFlexibleServer'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.Storage'
            }
          ]
        }
      }
      {
        name: 'snet-labvms'
        properties: {
          addressPrefix: '10.50.16.0/20'
          privateEndpointNetworkPolicies: 'Disabled'
          networkSecurityGroup: {
            id: labNsg.id
          }
        }
      }
    ]
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-labforge'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    workspaceCapping: {
      dailyQuotaGb: logAnalyticsDailyQuotaGb
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForDeployment: false
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
  }
}

resource postgresqlDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: postgresqlDnsZoneName
  location: 'global'
}

resource postgresqlDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresqlDnsZone
  name: 'link-labforge-vnet'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource postgresql 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: 'psql-labforge-${uniqueString(resourceGroup().id)}'
  location: location
  tags: {
    labforge: 'true'
    environment: 'staging'
  }
  sku: {
    name: postgresSkuName
    tier: postgresSkuTier
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUsername
    administratorLoginPassword: postgresAdminPassword
    dataEncryption: {
      type: 'SystemManaged'
    }
    replicationRole: 'Primary'
    storage: {
      storageSizeGB: postgresStorageSizeGB
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: databaseSubnetId
      privateDnsZoneArmResourceId: postgresqlDnsZone.id
    }
    highAvailability: {
      mode: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Disabled'
      passwordAuth: 'Enabled'
    }
  }
  dependsOn: [
    postgresqlDnsLink
  ]
}

resource gallery 'Microsoft.Compute/galleries@2022-03-03' = {
  name: galleryName
  location: location
  properties: {
    description: 'LabForge reusable course images'
  }
}

resource apiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
}

resource postgresScheduleRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'LabForge PostgreSQL Power Scheduler')
  properties: {
    roleName: 'LabForge PostgreSQL Power Scheduler'
    description: 'Allows the staging schedule workflow to read, start, and stop PostgreSQL Flexible Servers in the LabForge core resource group.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.DBforPostgreSQL/flexibleServers/read'
          'Microsoft.DBforPostgreSQL/flexibleServers/start/action'
          'Microsoft.DBforPostgreSQL/flexibleServers/stop/action'
        ]
        notActions: []
      }
    ]
    assignableScopes: [
      resourceGroup().id
    ]
  }
}

resource postgresScheduleRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, postgresSchedulerPrincipalId, postgresScheduleRole.id)
  scope: postgresql
  properties: {
    roleDefinitionId: postgresScheduleRole.id
    principalId: postgresSchedulerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource galleryReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(gallery.id, apiIdentity.id, 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
  scope: gallery
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'acdd72a7-3385-48ef-bd42-f606fba81ae7')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultSecretsOfficerAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, apiIdentity.id, 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7')
    principalId: apiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output appsSubnetId string = appsSubnetId
output labVmsSubnetId string = labVmsSubnetId
output databaseSubnetId string = databaseSubnetId
output galleryName string = gallery.name
output galleryId string = gallery.id
output apiPrincipalId string = apiIdentity.properties.principalId
output apiIdentityClientId string = apiIdentity.properties.clientId
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultId string = keyVault.id
output postgresServerName string = postgresql.name
