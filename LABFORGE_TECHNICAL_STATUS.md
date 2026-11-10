# LabForge Complete Technical Documentation

**Document version:** 2.1  
**Updated:** 9 November 2026  
**Repository:** `jesshhika/LAB-PLATFORM-`  
**Purpose:** Architecture, implementation status, Azure configuration, verification evidence, operations, remaining work, and delivery runbooks.

## 1. Executive summary

LabForge is a browser-based hands-on technical lab platform. Learners launch a temporary Windows lab VM, follow a side-by-side course guide, complete tasks, run automated validation, and track progress. Each learner receives isolated, private lab infrastructure for the duration of the session.

The repository contains:

- A Next.js learner and administrator web application.
- A FastAPI application for catalog, sessions, progress, validation, authentication boundaries, and administration.
- An RQ worker for VM lifecycle and Azure sandbox operations.
- PostgreSQL and Redis infrastructure.
- guacd and a Guacamole Lite WebSocket proxy for private browser RDP.
- Azure Bicep infrastructure.
- A Packer Windows Server image pipeline.
- Foundry course guides and VM validation scripts.
- CI/CD, budget, load-test, migration, and runbook artifacts.

Implementation status is split clearly between **code complete**, **locally verified**, and **Azure-live verified**. Azure authentication-dependent actions must still be executed against the target subscription before the platform can be considered production accepted.

### Current readiness check — 9 November 2026

- Backend tests: 18 passed locally and in the API container. Guacamole proxy tests: 4 passed. Ruff checks passed.
- Docker Compose configuration and all five reviewed Bicep entry/module files validate locally. The API migration chain applied successfully to an isolated local PostgreSQL database.
- Web lint and production build passed in the Docker image. The local web page, API health proxy, and course endpoint returned successful responses.
- A React state-update lint error in the admin sessions page was fixed. A missing Alembic revision link was fixed and covered by a migration-graph test.
- The isolated backend Compose stack passed its smoke tests and was removed. Full Compose startup hit a host-port conflict on `8080`, already occupied by the pre-existing `lab-guac-proxy-1` container. Existing `lab` containers were left running and unchanged.
- Read-only Azure inventory confirmed the LabForge core foundation and gallery image `1.0.4`; the Container Apps list was empty and `rg-labforge-labvms` had no VMs.
- Azure subscription, container-app, VM, and resource-group inventory calls succeeded, but PostgreSQL detail inspection still fails with a token-tenant mismatch. Azure writes/live acceptance were not attempted; no new Azure resources or costs were authorized.

**Handover decision:** not ready for production handover. Browser-RDP, live worker/session lifecycle, sandbox isolation, production deployment, and pilot acceptance remain unverified. The authorized spend cap is zero, so these cloud acceptance steps remain blocked until the user approves an explicit budget. Do not treat successful local tests or template compilation as cloud acceptance evidence.

## 2. Delivery status

| Phase | Code status | Verification status | Remaining evidence |
|---|---|---|---|
| 0 - Foundations | Complete | Docker, migrations, tests, lint, and Bicep validated locally | Live production infrastructure deployment |
| 1 - Golden image | Complete | Image `1.0.4` published; private VM provisioning observed | Latest tool packages and application validation inside image |
| 2 - Browser VM foundation | Implemented | Private VM created and deleted | Browser RDP through guacd/Guacamole |
| 3 - Authentication | Development implemented; production auth coded | Local token-free development accepted | Live Entra/OIDC tenant configuration |
| 4 - Lab workspace | Complete locally | API/UI behavior covered locally | Production browser/UAT testing |
| 5 - VM lifecycle | Implemented | Private creation evidence exists | Queue-backed worker and full cleanup/recovery acceptance |
| 6 - Progress and validation | Implemented | API/unit tests and validation scripts exist | Five scripts executed on a live VM |
| 7 - Sandbox isolation | Implemented | Unit/static validation only | Graph tenant, RG, role assignment, and cleanup live test |
| 8 - Administration | Implemented | API and UI implementation validated locally | Production RBAC and pilot workflow |
| 9 - Hardening and go-live | Partially implemented | CI and templates exist | Real deployment, policy, monitoring, load, and DR acceptance |

## 3. Repository layout

| Path | Responsibility |
|---|---|
| `web/` | Next.js learner and administrator interfaces |
| `api/app/` | FastAPI models, routes, authentication, services, database, queue, catalog |
| `api/migrations/versions/` | Alembic database migrations |
| `api/tests/` | FastAPI health and business logic tests |
| `worker/` | RQ VM lifecycle and Azure sandbox jobs |
| `guac-proxy/` | Guacamole Lite WebSocket proxy and session token validation |
| `labs/foundry/` | Course manifest, guide Markdown, and VM validation scripts |
| `images/foundry/` | Packer image pipeline and image-definition Bicep |
| `infra/modules/` | Core Azure, VM access, and governance Bicep modules |
| `infra/main.bicep` | Subscription-level infrastructure entry point |
| `.github/workflows/ci.yml` | Pull-request validation and deployment workflow |
| `k6/load-test.js` | Concurrent lab-launch load test |

## 4. System architecture

```text
Learner Browser
  |
  +-- Next.js Web --> FastAPI API --> PostgreSQL
  |                         |
  |                         +--> Redis/RQ --> Worker
  |                                              |
  |                                              +--> Azure Compute / Network
  |                                              +--> Azure Key Vault
  |                                              +--> Microsoft Graph / Entra
  |
  +-- WebSocket --> Guacamole Lite --> guacd --> Private Windows VM RDP
```

### 4.1 Frontend

The web application uses Next.js App Router, TypeScript, and Tailwind CSS. It provides:

- Course and lab discovery.
- Session launch and duplicate-session reuse.
- A guide and remote desktop split workspace.
- Persistent task and manual progress controls.
- Session timer, extension, and ending controls.
- Validation result presentation.
- Administrator course, learner, live-session, and report controls.

### 4.2 Backend

The API uses Python 3.11, FastAPI, SQLAlchemy 2, Pydantic v2, and Alembic. It owns session state, course catalog behavior, progress persistence, administrative operations, and read-only security boundaries.

### 4.3 Worker

The RQ worker performs Azure VM and sandbox actions:

- Queued session provisioning.
- Private NIC and private IP discovery.
- VM creation without public IPs.
- VM credential storage in Key Vault.
- Learner-password Run Command setup.
- Lab and sandbox resource cleanup.
- Session extension and expiration.
- Idle timeout handling.
- Partial provisioning rollback.
- Orphan resource reaping.

### 4.4 Remote desktop

Guacamole traffic is transported from the browser over WebSocket to `guac-proxy`, then to `guacd`, then to private Windows RDP. The connection token is:

- AES-encrypted.
- Bound to the session ID.
- Limited to private RFC1918 target addresses.
- Valid for two minutes.
- Protected by a shared cryptographic key held outside source control.

## 5. Data model

Alembic migrations define the core entities:

- `lab_sessions`: learner session, lab, lifecycle state, expiry, private IP, VM, resource group, credential secret names, and sandbox references.
- `lab_progress`: completed lab and completion method.
- `task_progress`: per-lab task completion with user, lab, and task index.
- `lab_users`: administrator/learner identity records.
- `courses`: managed course metadata.
- `enrollments`: learner/course enrollment and expiry.
- `audit_logs`: administrative actions such as creation, extension, ending, and shadow access.

Database migrations are available through the API container and local Compose workflow.

## 6. Azure foundation

### 6.1 Verified Azure configuration

| Setting | Current value |
|---|---|
| Subscription | Visual Studio Enterprise Subscription - MCT |
| Subscription ID | `2c61531c-da23-4b81-be54-7dea04212226` |
| Region | Central India |
| Core resource group | `rg-labforge-core` |
| Lab VM resource group | `rg-labforge-labvms` |
| Virtual network | `10.50.0.0/16` |
| Application subnet | `10.50.1.0/24` |
| Database subnet | `10.50.2.0/24` |
| Lab VM subnet | `10.50.16.0/20` |
| Compute Gallery | `galLabForge` |
| Image definition | `img-foundry` |
| Verified image | `1.0.4` |
| Learner VM | `Standard_B2s` |
| OS disk | `StandardSSD_LRS`, delete with VM |
| Warm pool | Zero |

### 6.2 Networking and isolation

The lab VM subnet accepts RDP only from the application subnet. The VM image and NIC must be associated with the lab VM subnet and must not receive public IP configuration. Guardrails in the worker reject missing private-IP information and provisioning attempts without an explicit subnet.

All lab resources should carry these tags:

- `labforge=true`
- `session_id=<LabSession.id>`
- `user_id=<learner identity>`
- `course=<course id>`

### 6.3 Cost-conscious defaults

- No warm pool.
- No public VM IP.
- `Standard_B2s` learner and builder size where quota permits.
- Burstable PostgreSQL `Standard_B1ms`.
- 32 GB PostgreSQL storage.
- No high availability.
- Seven-day PostgreSQL backup retention.
- Boot diagnostics disabled.
- Delete-on-VM managed OS disk behavior.
- 30-day Log Analytics retention target.
- Development database and local containers stopped when idle.
- Azure production resources created only for accepted deployment.

## 7. Implemented phase details

### Phase 0 - Foundations

Complete repository, Docker, migration, health, Azure foundation, and cost-control work is present. This includes:

- Docker Compose for the application, database, queue, RDP proxy, and guacd.
- PostgreSQL migration and local health checks.
- Redis-backed RQ worker.
- Azure Core Bicep for VNet, NSGs, PostgreSQL, Key Vault, managed identity, gallery, private DNS, and Log Analytics.
- Subscription Bicep entry point and governance module.
- Phase 0 validation scripts.
- Environment templates with no real secrets.

### Phase 1 - Golden image

The private Compute Gallery and image definition were created successfully. Image version `1.0.4` was published from the Foundry image pipeline. The course manifest uses this image version.

Packer creates only temporary image-builder resources. It must be run with an identified session ID and temporary resource cleanup review. Image versions are immutable; changes require a new image version.

### Phase 2 - Private VM foundation

A private VM launched successfully from image `1.0.4`. It received private IP `10.50.16.5`, had no public IP, and was deleted after acceptance. This evidence covers private VM networking and image boot, but does not replace end-to-end browser desktop acceptance.

### Phase 3 - Authentication

Production OIDC boundaries are coded in the API:

- Bearer-token validation.
- Issuer and audience configuration.
- JWKS retrieval.
- Learner, instructor, and administrator role resolution.
- Development identity fallback only outside production.

Remaining authentication work is live Entra tenant setup, stable object-ID mapping, approved group assignments, protected cookies or secure token storage, and UAT.

### Phase 4 - Lab workspace

The learner workspace includes:

- Course and lab navigation.
- Guide pagination.
- Task completion persistence.
- Manual completion.
- Session timer.
- Session extension.
- Session ending.
- Validation result UI.
- Desktop reconnect/fullscreen controls.
- Administrator live-session page with auto-refresh.

### Phase 5 - VM lifecycle

The worker implements queue-backed VM provisioning and lifecycle:

- Duplicate active-session reuse.
- Private NIC creation.
- Private IP discovery.
- VM creation from gallery image ID.
- Learner password setup through Run Command.
- VM and NIC cleanup.
- Delete-on-VM OS disk.
- VM credential storage.
- Session expiry and idle handling.
- Extension count and maximum lifetime.
- Rollback after partial provisioning failures.
- Orphan-session cleanup.
- Warm pool support at configurable zero/default.

### Phase 6 - Progress and validation

Progress and validation are implemented through:

- Per-user lab completion persistence.
- Per-task checkbox persistence.
- Completion percentages.
- Manual completion.
- Run Command validation scripts.
- Exact pass/fail JSON parsing.
- Course progress CSV export.
- Five Foundry validation scripts.

Live validation requires an active Azure VM from image `1.0.4`.

### Phase 7 - Azure sandbox identities

The implementation creates an isolated sandbox resource group and Microsoft Graph learner user in a dedicated labs tenant. The user receives a Contributor role assignment limited to the session resource group. Credentials are stored in Key Vault, and cleanup removes:

- Session sandbox resource group.
- Graph learner account.
- VM credential secrets.
- Azure sandbox credential secrets.
- VM and NIC resources.

Sandbox provisioning requires valid Graph application permissions and an explicit labs tenant. The production implementation must never reuse company-tenant identities.

### Phase 8 - Administration

Administrative implementation includes:

- Course create/update operations.
- Learner create operations.
- CSV learner import.
- Enrollment creation and expiry.
- Live-session listing.
- Session extension and end operations.
- Read-only shadow-token support.
- Per-course progress export.
- Audit-log records.

The shadow feature is role-restricted in code to administrator or instructor roles.

### Phase 9 - Cost, security, and delivery

Repository-level hardening includes:

- A subscription consumption budget with 50%, 80%, and 100% notifications.
- VM-size allowance beginning at `Standard_B2s`.
- GitHub Actions validation for Python, web, proxy, and Bicep.
- GitHub OIDC workflow design without stored Azure client secrets.
- Production approval environment.
- A 30-user k6 lab-launch scenario.
- Private networking, short-lived Guacamole tokens, Key Vault credentials, expiry cleanup, and audit logging.

## 8. Verification evidence

### 8.1 Automated repository verification

| Check | Recorded result |
|---|---|
| Backend pytest | 17 passed |
| Guacamole proxy Node tests | 4 passed |
| Python lint | Passed |
| Next.js production build | Passed in the validated baseline |
| Web ESLint | Passed in the validated baseline |
| Bicep compilation | Passed |
| Alembic migration | Passed |

The latest web npm restore/build result should be rerun because a prior npm `ECONNRESET` interrupted dependency restoration; it must not be inferred from older results.

### 8.2 Docker services

The Compose design provides PostgreSQL, Redis, API, worker, Next.js, guacd, and Guacamole proxy services. Persistent PostgreSQL data is intentionally retained by the named volume.

### 8.3 Azure evidence

Observed evidence:

- Private image `1.0.4` published.
- Standard B2s private VM received private IP.
- No public VM IP observed.
- VM cleanup confirmed after the test.

Not yet live-verified:

- Queue-backed real Azure worker provisioning.
- Browser RDP and remote-desktop interactions.
- Sandbox Graph user creation and cleanup.
- All five VM validation scripts.
- Production Container Apps deployment.
- Live monitoring, policy, budget, load test, and pilot acceptance.

## 9. Configuration and secrets

Copy `.env.example` to `.env` for local development. At minimum:

- Generate a 32-byte `GUAC_CRYPT_KEY`.
- Keep PostgreSQL credentials local.
- Do not commit `.env`.
- Do not commit bicepparam files or Azure credentials.
- Keep Azure tenant, audience, issuer, and JWKS values in environment or secret configuration.
- Keep VM passwords exclusively in Key Vault.
- Use managed identity or federated credentials in Azure-hosted workloads.

## 10. Local operations

PowerShell commands:

```powershell
Copy-Item .env.example .env
docker compose up --build
docker compose ps
```

API health:

```text
http://localhost:8000/api/health
```

Web interface:

```text
http://localhost:3000
```

Stop local resources:

```powershell
docker compose down
```

## 11. Azure deployment prerequisites

Before live deployment:

1. Authenticate locally with Azure CLI or a managed identity.
2. Select the intended subscription explicitly.
3. Confirm vCPU, VM-family, PostgreSQL, and Compute Gallery quota.
4. Confirm the dedicated labs tenant and Graph application permissions.
5. Supply a Key Vault URL, lab subnet ID, gallery image ID, and subscription ID.
6. Configure production OIDC issuer, audience, and JWKS URI.
7. Supply a budget notification recipient.
8. Deploy infrastructure at subscription scope only through an approved change.
9. Start the worker and API using managed identity credentials.

## 12. Acceptance checklist

### Networking and VM

- A learner VM is created only from a public-IP-free configuration.
- VM NIC uses the private lab subnet.
- VM receives an RFC1918 private IP.
- No public IP resource exists for the VM.
- RDP is reachable only from the application subnet.
- VM creation stops or rolls back if private IP discovery fails.

### Browser workspace

- Learner opens the course.
- Learner launches a lab.
- Duplicate launch reuses the active session.
- Guide and desktop display side by side.
- Keyboard, mouse, clipboard, reconnect, resize, and fullscreen work.
- Token expires and cannot continue without a new authorized session.

### Progress and validation

- Task progress persists after refresh.
- Lab progress survives VM deletion and learner logout.
- Course progress reports exact percent.
- Each validation script executes in the VM context.
- Validation output identifies pass/fail checks.

### Lifecycle and cleanup

- Heartbeat preserves active sessions.
- Idle timeout applies only after configured inactivity.
- Extension updates expiry and enforces maximum lifetime.
- Normal end deletes VM and NIC.
- Delete-on-VM removes the OS disk.
- Key Vault credentials are deleted.
- Sandbox RG and Graph learner are deleted.
- Orphan reaper removes untracked session resources.
- Duplicate cleanup is safe.

### Authentication and administration

- Production requests require valid OIDC bearer tokens.
- Stable Entra object IDs represent learners.
- Learners cannot invoke admin APIs.
- Instructors cannot perform tenant-changing operations.
- Read-only shadow access is limited to authorized roles.
- Administrative changes produce audit records.

## 13. Cost and resource controls

| Resource | Production control |
|---|---|
| Learner VMs | Create only while a session is active; delete at end/expiry |
| Warm pool | Zero by default |
| Public IP | Never create |
| VM size | `Standard_B2s` first; enforce SKU policy |
| OS disk | Standard SSD; delete with VM |
| Builder VM | Run only for image publication, then remove |
| PostgreSQL | Burstable tier, no HA, stop or delete inactive development database |
| Container Apps | Deploy only if production traffic is expected; scale to zero where suitable |
| Redis | Use managed only if production resilience requires it |
| Key Vault | Standard SKU; purge-protection and rotation procedures |
| Log Analytics | About 30-day retention; alert only on actionable conditions |
| Budget | Start at low monthly notification threshold; recipients configured before deployment |

## 14. Security controls

- Azure VM private IP only.
- NSG denies RDP outside the application subnet.
- Run Command used for learner setup, not passwords in source control.
- Key Vault stores VM and sandbox credentials.
- Short-lived Guacamole session tokens.
- OIDC bearer validation in production.
- Role-restricted administration and read-only shadow operations.
- Contributor role assignment scoped to one session resource group.
- Dedicated labs tenant separate from the company tenant.
- Audit logs for tenant-facing and session administrative operations.
- CI OIDC federation preferred over Azure secret credentials.
- Environment secret scanning and branch protection recommended.

## 15. Remaining work

### Azure and infrastructure

- Complete Azure authentication locally or with managed identity.
- Deploy and verify production Container Apps.
- Configure TLS and custom domain.
- Configure production Redis/PostgreSQL connectivity.
- Deploy the budget with real contacts.
- Enable Azure policies for public-IP denial, location restriction, SKU allowance, and required tags.
- Configure Key Vault access for API and worker identities.
- Configure managed Graph application permissions.
- Deploy monitoring and alerting.

### End-to-end live acceptance

- Run one queued `Standard_B2s` VM lifecycle against image `1.0.4`.
- Validate private browser desktop through guacd.
- Test reconnect, clipboard, keyboard, resize, and fullscreen.
- Run all five Foundry validation scripts.
- Create Graph learner and sandbox resource group.
- Assign and verify session-scoped Contributor access.
- Clean up VM, NIC, disk, Graph user, RG, and Key Vault secrets.
- Test extension, idle timeout, expiry, orphan cleanup, and partial rollback.

### Pilot readiness

- Restore and rerun Next.js dependencies, lint, and production build.
- Configure staging/production environments.
- Run 20–30 concurrent session load testing and Azure quota review.
- Run failure tests for VM loss, network loss, database loss, Redis loss, worker loss, and Azure credential loss.
- Perform a backup/restore test.
- Run one small internal pilot.
- Document support, incident, recovery, and cost-runbook ownership.

## 16. Incident and cleanup procedures

### End an active session

Use the API or administrator UI end-session operation. This triggers VM cleanup, secret cleanup, and sandbox cleanup. Verify the database status is terminal and query the Lab VM resource group for resources carrying the same `session_id`.

### Handle an orphaned session

Run the orphan-reaper worker path during maintenance. Confirm resources before deletion using session and `labforge=true` tags. Never delete resources based only on VM name fragments.

### Stop billable test services

- Delete learner and image-builder test VMs.
- Stop local Compose services.
- Stop development PostgreSQL if not needed.
- Remove temporary preview Container Apps or scaling environments.
- Remove stale Key Vault secrets.
- Review resources by `labforge`, `session_id`, and creation date.
- Confirm no public IP resources exist in Lab VM subscriptions or groups.

### Handle provisioning failure

1. Mark the session failed.
2. Remove VM, NIC, and prefixed disk resources by session ID.
3. Remove credential secrets.
4. Remove session sandbox RG and Graph account.
5. Record failed stage and Azure error details.
6. Requeue only after quota/network/image configuration is confirmed.

## 17. Recommended execution order

1. Restore and verify Next.js dependencies.
2. Run API, lint, proxy, migration, and Bicep checks.
3. Authenticate Azure using the intended identity.
4. Confirm subscription, quota, gallery, subnet, Key Vault, and tags.
5. Provision one private B2s VM and verify OS/image state.
6. Test browser RDP and Guacamole controls.
7. Run and inspect all five validation scripts.
8. Configure the dedicated labs tenant and Graph user provisioning.
9. Test sandbox isolation and cleanup.
10. Configure OIDC production roles.
11. Deploy a staging environment with low-cost scaling.
12. Run load and failure acceptance.
13. Configure budget, alerts, monitoring, policies, and runbooks.
14. Complete a small pilot.
15. Deploy production only after pilot acceptance.
