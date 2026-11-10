# LabForge staging acceptance runbook

This runbook describes a controlled staging deployment and temporary VM
acceptance test. The user authorized a maximum of **INR 3,000 total incremental
spend** for staging and one temporary VM acceptance test. This is an operator
stop limit, not an Azure-enforced cap. No deployment or billable acceptance VM
has been performed.

## Guardrails in this change

- At most 2 queued, provisioning, ready, or tearing-down VMs.
- At most 8 VM-hours per Asia/Kolkata calendar day.
- At most 120 minutes per session including its one allowed extension.
- 20-minute idle teardown; warm-pool size is 0.
- The API and worker allow only `Standard_B2s`; the Bicep template defines a
  matching lab-resource-group policy, not yet deployed.
- Lab VM NICs are provisioned with private IPs only; the Bicep template defines
  a policy to deny public IP resource creation, not yet deployed.
- PostgreSQL is privately networked. The worker runs its application reaper
  every 10 minutes and must be deployed on a network path that can reach the
  private database; GitHub-hosted runners do not connect to it.
- The workflow template intends to run PostgreSQL 8:00 AM–10:00 PM IST. It is
  not configured or active yet. It controls compute only; storage, backups,
  networking, and other resources may continue to incur charges while stopped.
- The Bicep template sets a monthly budget alert of 2,500 in subscription
  currency, filtered to `rg-labforge-core` and `rg-labforge-labvms`, with actual
  alerts at 50%, 80%, and 100%, plus a 100% forecast alert. It is not deployed
  and is not a hard spend cap.
- The Bicep template sets Log Analytics ingestion to 1 GiB/day and retention
  to 30 days. It is not deployed.

## Preflight

1. The target Visual Studio Enterprise subscription is enabled and its existing
   budget reports INR. The subscription also contains unrelated resource
   groups. Restrict resource changes to the LabForge resource groups and review
   all subscription-scope policy/budget changes before applying them.
2. Keep the approved total incremental-spend ceiling at INR 3,000, including
   PostgreSQL, VM compute, disks, network, logs, images, deployment, and
   cleanup. Stop if a cost cannot be estimated and kept within that ceiling.
   The existing subscription budget reported INR 8,387.12 in accumulated spend
   when checked on 10 November 2026; this is existing-period spend, not the
   incremental cost of this test.
3. Configure `budgetContactEmails` with monitored addresses and
   `postgresSchedulerPrincipalId` with the staging GitHub OIDC service
   principal object ID before deployment. Do not use the example placeholders.
4. Confirm quota and availability for `Standard_B2s` in `centralindia`.
5. Configure the GitHub `staging` environment with:
   - Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
     `AZURE_SUBSCRIPTION_ID`.
   - Variable: `AZURE_POSTGRES_SERVER_NAME`, copied from the Bicep deployment
     output.
   - An OIDC federated credential limited to this repository and environment.
6. Review the current worktree and Bicep what-if output. The 10 November
   what-if showed new budget, policies, policy assignments, a custom role, and
   role assignments; it also showed changes to the existing gallery description,
   PostgreSQL tags, Log Analytics daily quota (0.023 to 1 GiB/day), and a
   Key Vault role assignment. It used dummy what-if values and is not deployment
   approval. Review those changes and the actual identities/recipients again
   before any deployment.
7. The current Bicep entry point provisions foundations and governance only;
   it does not deploy the LabForge API, web app, worker, Redis, or Guacamole
   services. Do not treat this infrastructure what-if as an application
   staging deployment.
8. Azure MCP resource-group inventory succeeds for the target subscription,
   but its PostgreSQL command returns a 401 tenant-mismatch error. Resolve the
   MCP/CLI credential tenant before using that path for PostgreSQL operations;
   do not infer server state from the failed request.
9. Apply the API migrations before starting the application. Do not run
   acceptance against a database without the staging guardrail migration.

## Acceptance sequence

1. Verify the API reports healthy and the admin guardrail panel displays the
   configured concurrency and VM-hour limits.
2. Verify a launch is queued only when capacity and daily VM-hour headroom are
   available. Confirm an over-cap launch is refused with HTTP 429 and the
   expected `capacity` or `daily_budget` reason.
3. Launch only one temporary session. Verify its VM has a private address,
   the expected `session_id` tag, the approved size, and an auto-shutdown
   schedule.
4. Verify the browser lab connection works; then end the session and confirm
   VM, NIC, disk, shutdown schedule, and session secrets are removed.
5. Verify the idle timeout and maximum session lifetime each queue normal
   cleanup. Do not create a second VM unless the approved spend window permits.
6. Review budget and Log Analytics metrics, and confirm the PostgreSQL scheduled
   workflow starts/stops the expected server. Scheduled workflows can be
   delayed by GitHub; do not rely on them as a hard power-off control.
7. Record results, timestamps, resource IDs, and actual costs. Keep personal
   data and secrets out of the acceptance report.

## Stop and cleanup

- Stop acceptance immediately if a VM cannot be deleted, a resource is not
  tagged with its session ID, an unexpected public IP appears, or actual/forecast
  spend approaches the approved incremental limit.
- Use the worker's normal cleanup path first. The standalone
  `ops/reap_vms.py` tool is a recovery aid and must be run only from a network
  path that can reach the private PostgreSQL server. Begin with `--dry-run`;
  retain its default delete limit and do not use `--force` without incident
  approval.
- Confirm no lab VMs, NICs, unattached disks, schedules, or test images remain.
- Stop PostgreSQL after testing. If staging is no longer needed, remove its
  resources only after reviewing a separate deletion plan; do not delete the
  subscription or shared resources.

## Current status

The application controls, reaper, Bicep guardrails, and scheduled PostgreSQL
workflow are code changes only. Azure read-only inventory and a Bicep what-if
were performed, but no Azure resource deployment, budget assignment, workflow
run, or billable acceptance VM has been performed. The Azure MCP PostgreSQL
operation remains blocked by a credential tenant mismatch; resource inventory
and Azure CLI read-only checks are available, but this does not authorize or
validate a deployment.
