# Architecture

The dashboard is a self-hosted portal for security findings and code-coverage
posture. Scanner pollers publish snapshots. A normalizer maps those snapshots
onto a common finding model, stamps ownership from YAML, and writes PostgreSQL.
A FastAPI service reads the same store and configuration. A Next.js app and an
MCP server sit in front of that API.

## Runtime pieces

| Piece | Default local port | Role |
|---|---|---|
| PostgreSQL 16 | 5432 | Findings, events, snapshots, daily metrics, API tokens, DLQ |
| FastAPI (`app.api.main`) | 8000 | Authenticated read API, admin triggers, health |
| Normalizer (`app.normalizer.main`) | 8001 | Snapshot ingest, auto-close, config reload, DLQ ingest |
| Next.js frontend | 3000 | Role-aware UI; server and `/api/proxy` forward to the API |
| MCP server | stdio or 3001 | Read-only tools over the same API |
| Pollers | one-shot jobs | Dependabot, SonarCloud, Wiz, Jira pentest |

Optional production pieces (see `deploy/terraform/README.md`): Cloud Run
services and jobs, Cloud SQL, Pub/Sub, GCS, IAP, Secret Manager, and a nightly
rollup job.

## Data flow

```text
Scanner APIs
    │  poller job (Dependabot / SonarCloud / Wiz / Jira)
    ▼
Raw snapshot (local filesystem or GCS)
    │  ingest message {source, poll_id, raw_uri}
    ▼
Normalizer  ──maps──►  NormalizedFinding
    │  ownership.yaml + component registry
    ▼
PostgreSQL  (findings, finding_events, processed_payloads, daily_metrics)
    │
    ├─► FastAPI  ──►  Next.js (browser via IAP or X-Dev-Identity)
    └─► FastAPI  ──►  MCP (bearer token or local dev identity)
```

Locally, `INGEST_TRANSPORT=http` posts the snapshot pointer at the normalizer.
In GCP, `INGEST_TRANSPORT=pubsub` uses a topic, push subscription, and DLQ.

## Identity and authorization

Three verification strategies produce the same `Identity` object
(`backend/app/core/identity.py`):

- **Local:** Next.js stamps `X-Dev-Identity` from `DEV_IDENTITY_EMAIL`.
  `IDENTITY_BACKEND=dev` is allowed only when `ENV=local`.
- **Browser in GCP:** IAP authenticates at the load balancer. The frontend
  lifts `X-Goog-Authenticated-User-Email` into the same envelope and calls
  the API over the VPC.
- **MCP / API clients:** `Authorization: Bearer secdb_live_...` personal tokens
  created at `/settings/mcp`.

Authorization after identity is a single flag: the email is admin if it appears
in `config/rbac.yaml` `admin_emails`. Everyone who can reach the app can read
org-wide findings. `/admin` and SonarCloud-hosted Trivy issues
(`sonarcloud_trivy`) are admin-only. Developer, platform, and executive pages
are frontend layouts; they filter with query parameters such as `team` and
`source`, not with separate backend roles.

## Configuration vs data

YAML under `config/` is the source of truth for teams, components, SLA windows,
auto-close thresholds, coverage policy, and admin emails. The database stores
findings and derived metrics. Changing ownership YAML does not rewrite existing
rows until ingest or `make ownership-reresolve` runs.

## Repository layout

```text
backend/     FastAPI API, normalizer, pollers, CLI, MCP, Alembic
frontend/    Next.js App Router UI
config/      Runtime YAML (ExampleOrg demo committed)
docs/        This documentation
deploy/      Terraform for GCP
scripts/     Config validation, deploy, local identity helpers
```

Backend adapters (`RAW_STORE`, `INGEST_TRANSPORT`, `SECRET_BACKEND`,
`CONFIG_STORE`) switch between local filesystem/env/HTTP and GCS/GSM/Pub/Sub
without changing mapper or API code.
