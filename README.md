# LabForge

LabForge is a hands-on technical lab platform. Phase 0 provides a local
development stack and reviewable Azure foundations; it does not deploy Azure
resources automatically.

## Local development

Requirements: Docker Desktop with Compose, Node.js 20.9+, and (for local
non-container work) Python 3.11+.

1. Copy `.env.example` to `.env` if you need to override local defaults. The
   example credentials are for local development only.
2. Start the stack with `make up` (or `docker compose up --build`).
3. Open <http://localhost:3000>. The page should report **API healthy**.
4. The API health endpoint is <http://localhost:8000/api/health>.
5. Stop the stack with `make down`. Persistent PostgreSQL data remains in the
   `postgres-data` volume; `docker compose down -v` removes that data.

The local stack includes PostgreSQL, Redis, the API, RQ worker, Next.js web
app, guacd, and the Guacamole Lite WebSocket proxy.

## Azure foundations

Review `infra/README.md` and the Bicep templates before deployment. Deployment
creates billable Azure resources. The PostgreSQL administrator password is
read from the `LABFORGE_POSTGRES_ADMIN_PASSWORD` environment variable through
the ignored `infra/main.bicepparam` file; do not commit parameter files or
secrets. Use a dedicated lab subscription and verify quotas, network ranges,
resource names, and cost estimates first.
