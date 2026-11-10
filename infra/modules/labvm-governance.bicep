targetScope = 'resourceGroup'

param allowedVmSizesPolicyId string
param noPublicIpPolicyId string

resource allowedVmSizesAssignment 'Microsoft.Authorization/policyAssignments@2022-06-01' = {
  name: 'labforge-allowed-vm-sizes'
  properties: {
    displayName: 'LabForge: restrict lab VM sizes'
    policyDefinitionId: allowedVmSizesPolicyId
  }
}

resource noPublicIpAssignment 'Microsoft.Authorization/policyAssignments@2022-06-01' = {
  name: 'labforge-no-public-ip'
  properties: {
    displayName: 'LabForge: prohibit public IP resources'
    policyDefinitionId: noPublicIpPolicyId
  }
}
