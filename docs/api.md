# HTTP API

FastAPI app: `backend/app/api/main.py`, title `secdb API`. Local docs:
http://127.0.0.1:8000/docs once `make api-dev` is running.

Unauthenticated: `GET /health`. Everything else requires a verified identity
(IAP, `X-Dev-Identity` in local/dev backend, or `secdb_live_` bearer token).

## Read surfaces used by the UI

| Method | Path | Notes |
|---|---|---|
| GET | `/me` | Email, display name, `is_admin` |
| GET | `/findings` | Filters: `team`, `source`, `repo`, `asset`, `title`, `severity`, `status`, `sla_breached`; sort `sort_by` / `sort_dir` |
| GET | `/findings/wiz-by-category` | Wiz grouped for platform/developer Wiz pages |
| GET | `/findings/{id}` | Detail + events |
| GET | `/metrics/summary` | Headline KPIs |
| GET | `/metrics/trend` | Time series (`days`) |
| GET | `/metrics/top-teams` | Worst teams in scope |
| GET | `/metrics/top-services` | Worst assets in scope |
| GET | `/metrics/security-posture` | Per-source ratings |
| GET | `/metrics/sla-breaches` | Open critical/high past SLA |
| GET | `/coverage` | Coverage snapshot vs `coverage.yaml` |
| GET | `/scanners/health` | Per-source active / stale / dark / no_data |
| GET | `/teams` | Teams from ownership YAML |
| GET | `/components` | Parsed component registry |

## Writes (authenticated)

| Method | Path | Notes |
|---|---|---|
| POST | `/feedback` | In-app feedback |
| GET | `/me/mcp-config` | Hosted MCP URL snippet |
| POST | `/me/tokens` | Create personal API token (secret shown once) |
| GET | `/me/tokens` | List tokens |
| DELETE | `/me/tokens/{token_id}` | Revoke |

## Admin only

| Method | Path |
|---|---|
| GET | `/admin/pollers` |
| POST | `/admin/pollers/{source}/run` |
| GET | `/admin/dlq` |
| POST | `/admin/dlq/{event_id}/resolve` |
| GET | `/admin/ownership` |
| POST | `/admin/ownership/reresolve` |

`source` for poller run: `dependabot`, `sonarcloud`, `wiz`, `pentest`.

## Internal

`POST /internal/config-reload` reloads YAML caches. Production callers present
Pub/Sub/OIDC credentials (`verify_pubsub_oidc`). The normalizer exposes its
own `/internal/normalize`, `/internal/dlq`, and `/internal/config-reload`.

## Finding list semantics

- Repeatable `severity` and `status` are OR within the field, AND across
  fields.
- `sonarcloud_trivy` is omitted unless the caller is admin and asks for that
  `source` explicitly.
- SLA breach is SQL using `sla.yaml` windows so `total` and pagination stay
  correct.

Next.js never calls these URLs from the browser directly in production; it
uses the App Router proxy so identity headers stay on the server.
