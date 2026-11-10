targetScope = 'subscription'

@description('Azure region for the LabForge core resources.')
param location string = 'centralindia'

@description('PostgreSQL administrator login.')
param postgresAdminUsername string

@secure()
@description('Set through LABFORGE_POSTGRES_ADMIN_PASSWORD using the bicepparam file.')
param postgresAdminPassword string

@description('Development PostgreSQL SKU. Burstable is recommended for development.')
param postgresSkuName string = 'Standard_B1ms'

@allowed([
  'Burstable'
  'GeneralPurpose'
  'MemoryOptimized'
])
param postgresSkuTier string = 'Burstable'

@minValue(32)
@maxValue(16384)
param postgresStorageSizeGB int = 32

@minValue(1)
param monthlyBudgetAmount int = 2500

@minLength(1)
param budgetContactEmails array
@minLength(36)
@maxLength(36)
param postgresSchedulerPrincipalId string
@minValue(1)
@maxValue(100)
param logAnalyticsDailyQuotaGb int = 1

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
    postgresSkuName: postgresSkuName
    postgresSkuTier: postgresSkuTier
    postgresStorageSizeGB: postgresStorageSizeGB
    logAnalyticsDailyQuotaGb: logAnalyticsDailyQuotaGb
    postgresSchedulerPrincipalId: postgresSchedulerPrincipalId
  }
}

module labVmAccess './modules/labvm-access.bicep' = {
  name: 'labforge-labvm-access'
  scope: labVmsResourceGroup
  params: {
    apiPrincipalId: core.outputs.apiPrincipalId
  }
}

module governance './modules/governance.bicep' = {
  name: 'labforge-governance'
  scope: subscription()
  params: {
    monthlyBudgetAmount: monthlyBudgetAmount
    budgetContactEmails: budgetContactEmails
  }
}

module labVmGovernance './modules/labvm-governance.bicep' = {
  name: 'labforge-labvm-governance'
  scope: labVmsResourceGroup
  params: {
    allowedVmSizesPolicyId: governance.outputs.allowedVmSizesPolicyId
    noPublicIpPolicyId: governance.outputs.noPublicIpPolicyId
  }
}

output appsSubnetId string = core.outputs.appsSubnetId
output labVmsSubnetId string = core.outputs.labVmsSubnetId
output databaseSubnetId string = core.outputs.databaseSubnetId
output galleryName string = core.outputs.galleryName
output apiIdentityClientId string = core.outputs.apiIdentityClientId
output keyVaultUri string = core.outputs.keyVaultUri
output postgresServerName string = core.outputs.postgresServerName
