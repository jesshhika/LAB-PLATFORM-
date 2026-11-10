targetScope = 'subscription'

param allowedVmSizes array = [
  'Standard_B2s'
]
param monthlyBudgetAmount int = 2500
@minLength(1)
param budgetContactEmails array
param budgetStartDate string = utcNow('yyyy-MM-01')

var budgetName = 'labforge-monthly-budget'

resource labBudget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: budgetName
  properties: {
    category: 'Cost'
    amount: monthlyBudgetAmount
    timeGrain: 'Monthly'
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [
          'rg-labforge-core'
          'rg-labforge-labvms'
        ]
      }
    }
    timePeriod: {
      startDate: budgetStartDate
    }
    notifications: {
      Actual_GreaterThan_50_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 50
        contactEmails: budgetContactEmails
        thresholdType: 'Actual'
      }
      Actual_GreaterThan_80_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        contactEmails: budgetContactEmails
        thresholdType: 'Actual'
      }
      Actual_GreaterThan_100_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        contactEmails: budgetContactEmails
        thresholdType: 'Actual'
      }
      Forecasted_GreaterThan_100_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        contactEmails: budgetContactEmails
        thresholdType: 'Forecasted'
      }
    }
  }
}

resource allowedVmSizesPolicy 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'labforge-allowed-vm-sizes'
  properties: {
    policyType: 'Custom'
    mode: 'Indexed'
    displayName: 'LabForge: restrict lab VM sizes'
    description: 'Only approved, cost-bounded VM sizes may be created in the LabForge lab resource group.'
    metadata: {
      category: 'Compute'
    }
    policyRule: {
      if: {
        allOf: [
          {
            field: 'type'
            equals: 'Microsoft.Compute/virtualMachines'
          }
          {
            field: 'Microsoft.Compute/virtualMachines/hardwareProfile.vmSize'
            notIn: allowedVmSizes
          }
        ]
      }
      then: {
        effect: 'Deny'
      }
    }
  }
}

resource noPublicIpPolicy 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'labforge-no-public-ip'
  properties: {
    policyType: 'Custom'
    mode: 'All'
    displayName: 'LabForge: prohibit public IP resources'
    description: 'Public IP resources are not allowed in the LabForge lab resource group.'
    metadata: {
      category: 'Network'
    }
    policyRule: {
      if: {
        field: 'type'
        equals: 'Microsoft.Network/publicIPAddresses'
      }
      then: {
        effect: 'Deny'
      }
    }
  }
}

output allowedVmSizes array = allowedVmSizes
output allowedVmSizesPolicyId string = allowedVmSizesPolicy.id
output noPublicIpPolicyId string = noPublicIpPolicy.id
