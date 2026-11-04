You are helping build LabForge, a hands-on lab delivery platform. Learners
launch technical labs with a Windows VM in the browser, a side-by-side guide,
and per-lab progress tracking.

Stack:
- Frontend: Next.js App Router, TypeScript, Tailwind CSS
- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2
- Database and queue: PostgreSQL, Redis, RQ
- Azure: azure-identity, Azure management SDKs, Microsoft Graph, Key Vault
- Remote desktop: guacd, guacamole-lite, guacamole-common-js
- Infrastructure: Bicep and Azure Container Apps
- Monorepo: web, api, worker, guac-proxy, infra, images, labs

Rules:
- Never put secrets in source control; use environment variables or Key Vault.
- Lab VMs must have private IPs only; never create public IPs for them.
- Tag every session resource with session_id and ensure cleanup deletes it.
- Keep code typed, small, testable, and covered by focused tests.
