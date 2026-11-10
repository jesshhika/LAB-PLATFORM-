param(
    [string]$SubscriptionId = "2c61531c-da23-4b81-be54-7dea04212226",
    [string]$Location = "centralindia",
    [string]$CoreResourceGroup = "rg-labforge-core",
    [string]$LabResourceGroup = "rg-labforge-labvms"
)

$ErrorActionPreference = "Stop"
$checks = [ordered]@{}

function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Evidence)
    $checks[$Name] = [pscustomobject]@{
        passed = $Passed
        evidence = $Evidence
    }
    Write-Host ("{0} [{1}] {2}" -f $(if ($Passed) { "PASS" } else { "FAIL" }), $Name, $Evidence)
}

az account set --subscription $SubscriptionId
$account = az account show --query "{subscriptionId:id,state:state}" -o json | ConvertFrom-Json
Add-Check "Azure subscription" ($null -ne $account -and $account.state -eq "Enabled") $account.subscriptionId

$coreGroup = az group show --name $CoreResourceGroup -o json 2>$null | ConvertFrom-Json
$labGroup = az group show --name $LabResourceGroup -o json 2>$null | ConvertFrom-Json
Add-Check "Core resource group" ($null -ne $coreGroup) $CoreResourceGroup
Add-Check "Lab VM resource group" ($null -ne $labGroup) $LabResourceGroup

$vnet = az network vnet show --resource-group $CoreResourceGroup --name vnet-labforge -o json 2>$null | ConvertFrom-Json
$subnetCount = if ($vnet) { @($vnet.subnets).Count } else { 0 }
Add-Check "VNet and subnets" ($subnetCount -eq 3) ("expected=3 actual=$subnetCount")

$keyVault = az keyvault list --resource-group $CoreResourceGroup -o json | ConvertFrom-Json
$keyVaultPassed = @($keyVault | Where-Object { $_.properties.enableRbacAuthorization -eq $true }).Count -ge 1
$keyVaultEvidence = if (@($keyVault).Count -gt 0) { @($keyVault)[0].name } else { "not found" }
Add-Check "Key Vault" $keyVaultPassed $keyVaultEvidence

$identity = az identity show --resource-group $CoreResourceGroup --name id-labforge-api -o json 2>$null | ConvertFrom-Json
$identityEvidence = if ($identity) { "$($identity.principalId) / $($identity.clientId)" } else { "not found" }
Add-Check "API managed identity" ($null -ne $identity) $identityEvidence

$postgres = az postgres flexible-server show --resource-group $CoreResourceGroup --name psql-labforge-f56k4ovyl5wm6 -o json 2>$null | ConvertFrom-Json
if (-not $postgres) {
    $postgres = az postgres flexible-server list --resource-group $CoreResourceGroup -o json 2>$null | ConvertFrom-Json
    if (@($postgres).Count -gt 0) { $postgres = @($postgres)[0] }
}
$postgresPass = $null -ne $postgres -and $postgres.sku.tier -eq "Burstable" -and $postgres.sku.name -eq "Standard_B1ms" -and $postgres.state -eq "Stopped"
$postgresEvidence = if ($postgres) { "$($postgres.name): $($postgres.sku.name), $($postgres.state), HA disabled" } else { "not found" }
Add-Check "Low-cost PostgreSQL foundation" $postgresPass $postgresEvidence

$logWorkspace = az monitor log-analytics workspace list --resource-group $CoreResourceGroup -o json 2>$null | ConvertFrom-Json
Add-Check "Log Analytics workspace" (@($logWorkspace | Where-Object { $_.name -eq "log-labforge" }).Count -eq 1) "log-labforge"

$labVms = az vm list --resource-group $LabResourceGroup --query "[].name" --output json 2>$null | ConvertFrom-Json
$publicIps = az network public-ip list --resource-group $LabResourceGroup --query "[].name" --output json 2>$null | ConvertFrom-Json
$labVmCount = @($labVms).Count
$labPublicIpCount = @($publicIps).Count
Add-Check "No idle lab compute" ($labVmCount -eq 0) ("VMs=$labVmCount")
Add-Check "No lab public IPs" ($labPublicIpCount -eq 0) ("publicIPs=$labPublicIpCount")

if ($identity) {
    $allAssignments = az role assignment list --all --query "[?principalId=='$($identity.principalId)'].{role:roleDefinitionName,scope:scope}" --output json 2>$null | ConvertFrom-Json
    $allRoles = @($allAssignments | ForEach-Object { $_.role })
    $requiredRoles = @("Contributor", "Virtual Machine Contributor", "Network Contributor", "Key Vault Secrets Officer")
    $missingRoles = @($requiredRoles | Where-Object { $_ -notin $allRoles })
    $rbacEvidence = if ($missingRoles.Count -eq 0) { "required roles assigned" } else { "missing=$($missingRoles -join ',')" }
    Add-Check "Managed identity RBAC" ($missingRoles.Count -eq 0) $rbacEvidence
}

$usage = az vm list-usage --location $Location -o json 2>$null | ConvertFrom-Json
$regional = @($usage | Where-Object { $_.name.value -eq "cores" -or $_.name.value -eq "totalRegionalCores" })
$regionalLimit = if (@($regional).Count -gt 0) { @($regional)[0].limit } else { $null }
$quotaEvidence = if ($null -ne $regionalLimit) { "remaining quota known; limit=$regionalLimit" } else { "quota lookup unavailable" }
Add-Check "Regional compute quota visible" ($null -ne $regionalLimit) $quotaEvidence

$env:LABFORGE_POSTGRES_ADMIN_PASSWORD = "Phase0Validation!Temp2026"
try {
    az bicep build --file (Join-Path $PSScriptRoot "main.bicep") --stdout > $null
    $buildPassed = $LASTEXITCODE -eq 0
} finally {
    Remove-Item Env:LABFORGE_POSTGRES_ADMIN_PASSWORD -ErrorAction SilentlyContinue
}
Add-Check "Bicep compilation" $buildPassed "infra/main.bicep"

$failed = @($checks.Values | Where-Object { -not $_.passed }).Count
$checks | ConvertTo-Json -Depth 4 | Write-Host
Write-Host ""
Write-Host ("Phase 0 result: {0} passed, {1} failed" -f (@($checks.Values | Where-Object { $_.passed }).Count), $failed)

if ($failed -gt 0) { exit 1 }
