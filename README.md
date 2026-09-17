# Unified Security Dashboard

Unified Security Dashboard is a self-hosted security findings and coverage portal. It
normalizes results from optional security tools, assigns findings through YAML-owned
component metadata, stores them in PostgreSQL, and serves role-aware operational and
executive views.

## Architecture

- FastAPI backend: API, normalizer, pollers, CLI, and MCP endpoint.
- Next.js frontend: developer, platform, executive, and administration views.
- PostgreSQL: findings, snapshots, audit data, and rollups.
- YAML configuration: ownership, component scope, RBAC, SLA, auto-close, coverage,
  Jira pentest, and Wiz mappings.
- Optional GCP deployment: Cloud Run, Cloud SQL, Pub/Sub, GCS, IAP, and Secret Manager
  under `deploy/terraform`.

Pollers publish scanner snapshots to the normalizer. The normalizer resolves ownership
from `config/`, updates PostgreSQL, and records snapshot-driven lifecycle changes. The
API reads the same configuration and exposes data to the frontend and MCP clients.

## Prerequisites

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm
- Docker with Docker Compose
- GNU Make
- Terraform and Google Cloud CLI only for GCP deployment

## Local setup

```bash
cp .env.local.example .env.local
make install
make postgres-up
make migrate
```

Start the services in separate terminals:

```bash
make api-dev
make normalizer-dev
make frontend-install
make frontend-dev
```

Open `http://localhost:3000`. The committed ExampleOrg configuration is fictional and
safe for a local demo. Set `DEV_IDENTITY_EMAIL=admin@example.com` for administrator
access or use `make dev-as-admin`.

## Test and validation

```bash
make validate-config
make lint
make test
make frontend-typecheck
make frontend-build
terraform -chdir=deploy/terraform fmt -check -recursive
terraform -chdir=deploy/terraform init -backend=false
terraform -chdir=deploy/terraform validate
```

## Configuration

Production configuration lives in `config/`:

- `ownership.yaml`: pillars, teams, members, and scanner asset ownership.
- `component_registry.yaml`: canonical components, repositories, scanner projects,
  application grouping, and dashboard views.
- `component_scope.yaml`: compact executive/application/service scope map.
- `rbac.yaml`: explicit administrator email allowlist.
- `sla.yaml` and `auto_close.yaml`: remediation windows and snapshot close policy.
- `coverage.yaml`: inventory denominator, thresholds, projects, and exceptions.
- `jira_pentest.yaml`: optional Jira connector mapping.
- `wiz_service_team_map.yaml`, `wiz_subscription_pillar.yaml`, and
  `wiz_service_overrides.yaml.example`: optional Wiz ownership helpers.

Keep team keys aligned across ownership, registry, scope, and Wiz files. Run
`make validate-config` after every configuration change. Terraform uploads runtime
configuration to the deployment's config bucket.

## Optional integrations

All integrations are optional for local UI development:

- GitHub Dependabot: `GITHUB_ORG` and `DEPENDABOT_PAT`.
- SonarCloud: `SONAR_ORG`/`SONAR_ORGS` and `SONAR_TOKEN`.
- Wiz: `WIZ_API_URL`, `WIZ_CLIENT_ID`, and `WIZ_CLIENT_SECRET`.
- Jira pentest findings: `JIRA_BASE_URL`, `JIRA_API_EMAIL`, and `JIRA_API_TOKEN`.
- Slack failure alerts: `SLACK_WEBHOOK_URL`.
- GCP managed deployment and secret storage.

Never commit credentials. Copy `.env.local.example` and populate only integrations you
intend to run.

## GCP deployment

See `deploy/terraform/README.md`. Supply real project IDs, DNS, IAP principals,
repository identity, and integration settings through a non-committed `.tfvars` file.
Cloud Build configurations at the repository root build the standalone backend and
frontend images; they do not depend on a parent monorepo.

## License

MIT. See `LICENSE`.
