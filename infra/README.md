# Azure foundations

These Bicep templates create the LabForge core and lab-VM resource groups,
network, Key Vault, Log Analytics workspace,
private PostgreSQL Flexible Server, Compute Gallery, and backend managed
identity/role assignments. Subscription governance adds a monthly budget,
lab-resource-group policies for VM sizes and public IP resources, and a
resource-scoped PostgreSQL start/stop role for the scheduled workflow.

**Review and estimate costs before deployment.** The templates are not applied
by the local Docker workflow. Use a dedicated lab subscription, confirm the
region and quotas, and have an administrator review the identity permissions.
The app subnet is delegated to Container Apps. A separate delegated database
subnet and private DNS zone are included because PostgreSQL Flexible Server
private networking requires them. All three subnets are declared inline on
the VNet so deployments retain the existing subnets and their
service-association links; do not remove or split these definitions while the
Container Apps environment or PostgreSQL server uses them.
The Compute Gallery remains private to this subscription; cross-subscription
and community sharing are not enabled.
PostgreSQL defaults to `Standard_B1ms` (Burstable) in Central India for the
development environment, with 32 GiB storage and High Availability disabled.
The SKU and storage size are parameterized so a workload can be validated on the
smallest tier before increasing capacity. The templates explicitly retain system-managed data encryption
and the primary replication role so future What-If previews do not propose
removing those server defaults.
The Log Analytics workspace keeps 30 days of data and limits ingestion to
1 GiB/day. Subscription budget alerts are configured at 50%, 80%, 100% actual,
and 100% forecasted spend, with a default amount of 2,500 in the subscription's
currency, filtered to the two LabForge resource groups so unrelated
subscription workloads are excluded. Verify the subscription currency is INR
and set a real
`budgetContactEmails` list before deployment. Budget alerts and the Log
Analytics daily quota do not cap total Azure spending.

The lab VM resource group denies VM sizes outside `allowedVmSizes` (default
`Standard_B2s`) and blocks creation of public IP resources. The VM provisioner
also creates private-only NICs. The PostgreSQL schedule workflow stops the
server at 10:00 PM IST and starts it at 8:00 AM IST; it does not stop storage
charges. Configure the repository's `staging` environment with the OIDC
secrets `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID`, and
the variable `AZURE_POSTGRES_SERVER_NAME`. Pass the OIDC principal object ID as
`postgresSchedulerPrincipalId` to grant only server read/start/stop actions.
The schedule can be manually dispatched to start or stop the server.

See [STAGING_ACCEPTANCE.md](./STAGING_ACCEPTANCE.md) for staging preflight,
acceptance, and cleanup steps. These changes have not been deployed.

The PostgreSQL password is read from the environment, not stored in the
parameter file. In PowerShell, set it for the current process and deploy:

```powershell
$env:LABFORGE_POSTGRES_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', (Read-Host -AsSecureString "PostgreSQL admin password")).Password
az deployment sub create --location centralindia --template-file infra/main.bicep --parameters infra/main.bicepparam
Remove-Item Env:LABFORGE_POSTGRES_ADMIN_PASSWORD
```

Validate the deployed Phase 0 foundation without creating VMs or starting
PostgreSQL:

```powershell
make validate-phase0
# or
powershell -NoProfile -ExecutionPolicy Bypass -File infra/validate-phase0.ps1
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
