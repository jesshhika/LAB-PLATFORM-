# LabForge

LabForge is a hands-on technical lab platform. Phase 0 provides a local
development stack and reviewable Azure foundations; it does not deploy Azure
resources automatically.

## Local development

Requirements: Docker Desktop with Compose, Node.js 20.9+, and (for local
non-container work) Python 3.11+.

1. Copy `.env.example` to `.env` and generate a local proxy key. The example
   credentials are for local development only:

   ```powershell
   Copy-Item .env.example .env
   $bytes = New-Object byte[] 16
   $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
   $rng.GetBytes($bytes)
   $rng.Dispose()
   $key = -join ($bytes | ForEach-Object { $_.ToString("x2") })
   (Get-Content .env) -replace '^GUAC_CRYPT_KEY=.*$', "GUAC_CRYPT_KEY=$key" |
     Set-Content .env -Encoding ascii
   ```

   Keep `.env` local; the Guacamole key must match between the API and proxy.
2. Start the stack with `make up` (or `docker compose up --build`).
3. Open <http://localhost:3000>. The page should report **API healthy**.
4. The API health endpoint is <http://localhost:8000/api/health>.
5. Stop the stack with `make down`. Persistent PostgreSQL data remains in the
   `postgres-data` volume; `docker compose down -v` removes that data.

The local stack includes PostgreSQL, Redis, the API, RQ worker, Next.js web
app, guacd, and the Guacamole Lite WebSocket proxy.

## Lab phases in progress

The Foundry image build, private-IP Guacamole token flow, course guides,
workspace, and persisted manual/VM validation progress are implemented as local
code. The development API identity is only for local testing; learner
authentication and automated VM provisioning are outside this phase scope.
Apply the API migrations with `make migrate` before using persisted progress.

The proxy accepts only short-lived tokens (two minutes) and logs connection
start/end events by session ID. Session credentials are fetched from Key Vault
at runtime; no Azure credentials or VM passwords belong in source control.

## Staging VM cost controls

The API enforces the VM concurrency and daily VM-hour caps before queueing
provisioning. PostgreSQL transaction locking serializes launch reservations;
the daily cap reserves the remaining maximum session time for active and queued
sessions, plus the proposed session, to prevent concurrent launches from
overshooting the cap. Guardrail query failures refuse the launch. Actual daily
usage is calculated in SQL for the current Asia/Kolkata calendar day from each
VM session's recorded `started_at` and `ended_at` timestamps. The new meter starts after the
`0004_staging_cost_guardrails` migration; it does not invent historic VM start
times for existing rows.

The defaults below are conservative staging controls. Pydantic validates them
when application settings load; do not treat Azure budget notifications as a
hard spending cap.

| Variable | Default | Purpose |
| --- | --- | --- |
| `MAX_CONCURRENT_VMS` | `2` | Maximum queued, provisioning, ready, or tearing-down VMs. |
| `SESSION_MAX_MINUTES` | `120` | Maximum elapsed time from VM creation through extension. |
| `MAX_EXTENSIONS` | `1` | Maximum learner or admin extensions per session. |
| `IDLE_TIMEOUT_MINUTES` | `20` | Idle time before normal session teardown is queued. |
| `DAILY_VM_HOURS_CAP` | `8` | Aggregate VM-hours allowed per Asia/Kolkata day. |
| `ALLOWED_VM_SIZES` | `Standard_B2s` | Comma-separated VM sizes accepted by the API and worker. |
| `WARM_POOL_SIZE` | `0` | Staging warm-pool setting; keep at zero to avoid idle compute. |
| `VM_AUTOSHUTDOWN_TIME` | `2100` | Azure daily VM shutdown time in `HHMM` format. |
| `VM_AUTOSHUTDOWN_TZ` | `India Standard Time` | Azure timezone identifier for auto-shutdown. |
| `SESSION_EXTENSION_MINUTES` | `15` | Duration added by each permitted extension, bounded by the session maximum. |

Use the staging defaults in `.env` or the deployment environment, not values
copied into source code. Apply migrations with `make migrate` before running
the updated API. A capacity refusal returns HTTP 429 with a JSON `reason`
(`capacity` or `daily_budget`) and is recorded in the audit log.

Cloud image builds, test VMs, and other billable resources have not been
created. Review `images/foundry/README.md` and obtain approval before running
the Packer build or creating Azure resources. Phase 1 image verification and
the browser RDP acceptance test require those resources.

## Azure foundations

Review `infra/README.md` and the Bicep templates before deployment. Deployment
creates billable Azure resources. The PostgreSQL administrator password is
read from the `LABFORGE_POSTGRES_ADMIN_PASSWORD` environment variable through
the ignored `infra/main.bicepparam` file; do not commit parameter files or
secrets. Use a dedicated lab subscription and verify quotas, network ranges,
resource names, and cost estimates first.
