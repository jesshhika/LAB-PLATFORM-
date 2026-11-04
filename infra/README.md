# Azure foundations

These Bicep templates create the LabForge core and lab-VM resource groups,
network, Key Vault, Log Analytics workspace, Container Apps environment,
private PostgreSQL Flexible Server, Compute Gallery, and backend managed
identity/role assignments.

**Review and estimate costs before deployment.** The templates are not applied
by the local Docker workflow. Use a dedicated lab subscription, confirm the
region and quotas, and have an administrator review the identity permissions.
The app subnet is delegated to Container Apps. A separate delegated database
subnet and private DNS zone are included because PostgreSQL Flexible Server
private networking requires them.
The Compute Gallery remains private to this subscription; cross-subscription
and community sharing are not enabled.
PostgreSQL uses `Standard_D2s_v3` (General Purpose) in Central India because
Azure rejected the Burstable `Standard_B1ms` and `Standard_B2s` SKUs during
provisioning.

The PostgreSQL password is read from the environment, not stored in the
parameter file. In PowerShell, set it for the current process and deploy:

```powershell
$env:LABFORGE_POSTGRES_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host -AsSecureString "PostgreSQL admin password")).Password
az deployment sub create --location centralindia --template-file infra/main.bicep --parameters infra/main.bicepparam
Remove-Item Env:LABFORGE_POSTGRES_ADMIN_PASSWORD
```

`infra/main.bicepparam` is ignored by Git. It uses
`readEnvironmentVariable('LABFORGE_POSTGRES_ADMIN_PASSWORD')`; create the file
from `main.bicepparam.example` before deployment.

If the core resources already exist and only PostgreSQL needs retrying, use
`postgresql.bicep` at resource-group scope so the retry does not redeploy the
network or Container Apps environment:

```powershell
az deployment group validate --resource-group rg-labforge-core --template-file infra/postgresql.bicep --parameters postgresAdminPassword=$env:LABFORGE_POSTGRES_ADMIN_PASSWORD
az deployment group what-if --name labforge-postgresql-preview --resource-group rg-labforge-core --template-file infra/postgresql.bicep --parameters postgresAdminPassword=$env:LABFORGE_POSTGRES_ADMIN_PASSWORD
az deployment group create --name labforge-postgresql --resource-group rg-labforge-core --template-file infra/postgresql.bicep --parameters postgresAdminPassword=$env:LABFORGE_POSTGRES_ADMIN_PASSWORD
```
