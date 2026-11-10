targetScope = 'resourceGroup'

@description('PostgreSQL administrator login.')
param postgresAdminUsername string = 'labforgeadmin'

@secure()
@description('Set through LABFORGE_POSTGRES_ADMIN_PASSWORD.')
param postgresAdminPassword string

param postgresSkuName string = 'Standard_B1ms'
param postgresSkuTier string = 'Burstable'
param postgresStorageSizeGB int = 32

var location = resourceGroup().location

resource vnet 'Microsoft.Network/virtualNetworks@2023-09-01' existing = {
  name: 'vnet-labforge'
}

resource databaseSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-09-01' existing = {
  parent: vnet
  name: 'snet-db'
}

resource postgresqlDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' existing = {
  name: 'labforge.postgres.database.azure.com'
}

resource postgresql 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: 'psql-labforge-${uniqueString(resourceGroup().id)}'
  location: location
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
      delegatedSubnetResourceId: databaseSubnet.id
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
}

output serverName string = postgresql.name
output serverFqdn string = postgresql.properties.fullyQualifiedDomainName
