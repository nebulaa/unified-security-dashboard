# Local development

Run the full stack on one machine: Docker Postgres, FastAPI, the normalizer,
and Next.js. Scanner credentials are optional; the UI works against empty
tables plus the committed ExampleOrg YAML.

## Prerequisites

- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- Docker with Docker Compose
- GNU Make

The Makefile creates `backend/.venv` with `uv venv --python /usr/local/bin/python3.13`.
If your interpreter lives elsewhere, point `PYTHON_HOST` at it when you run
`make venv`.

## First-time setup

```bash
cp .env.local.example .env.local
make install
make postgres-up
make migrate
make frontend-install
```

`.env.local` is gitignored. The example already sets `ENV=local`,
`IDENTITY_BACKEND=dev`, local Postgres URLs, `NORMALIZER_URL`,
`API_BASE_URL=http://localhost:8000`, and
`DEV_IDENTITY_EMAIL=admin@example.com` (listed in `config/rbac.yaml`).

Leave Dependabot, Sonar, Wiz, and Jira placeholders empty until you want a
real poll. Never commit filled credentials.

## Start the services

Use four terminals (or background jobs):

```bash
make postgres-up          # already running after first setup
make api-dev              # http://127.0.0.1:8000
make normalizer-dev       # http://127.0.0.1:8001
make frontend-dev         # http://localhost:3000
```

Open http://localhost:3000. Admins land on `/admin`; everyone else on
`/executive`. Switch identity without editing YAML:

```bash
make dev-as-admin         # frontend as first email in rbac.yaml
make dev-as-member        # frontend as developer@example.com
```

`make bootstrap` is `install` + `postgres-up` + `migrate`.

## Optional ingest

With the normalizer up and real tokens in `.env.local`:

```bash
make poller-dependabot
make poller-sonarcloud
make poller-wiz
make poller-jira-pentest
```

Prototype coverage without cloud credentials:

```bash
make coverage-sample
```

Nightly-style metrics after you have findings:

```bash
make rollup-backfill
```

## Checks

```bash
make validate-config
make lint
make test
make frontend-typecheck
make frontend-build
```

## Postgres already exists

`make postgres-up` runs `docker-compose up -d postgres` and names the container
`secdb-postgres`. If a leftover container with that name is already running
(or stopped), Compose may fail with a name conflict. Start or reuse it:

```bash
docker start secdb-postgres
docker inspect -f '{{.State.Health.Status}}' secdb-postgres
```

Then run migrations without going through Compose:

```bash
cd backend && ../backend/.venv/bin/python -m app.migrate upgrade head
```

Wipe local data only when you intend to: `make postgres-reset`.

## Ports that must stay free

| Port | Process |
|---|---|
| 3000 | Next.js |
| 5432 | Postgres |
| 8000 | API |
| 8001 | Normalizer |
| 3001 | Optional `make mcp-http-dev` |
| 9080 / 9082 | Optional Cloud Run proxies (`make cloud-proxy-api`, `make cloud-proxy-frontend`) |

Do not use 8080/8081 for local proxies; Cloud Run images listen on 8080 and
8081 is easy to confuse with the normalizer.

## MCP against the local API

With `make api-dev` running:

```bash
make mcp-dev
```

stdio is the default. HTTP on port 3001: `make mcp-http-dev`. Client setup is
in [user/mcp-server.md](user/mcp-server.md).
