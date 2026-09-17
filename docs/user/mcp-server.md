# MCP server

The dashboard exposes a read-only [MCP](https://modelcontextprotocol.io) server
so coding agents can list findings, SLA breaches, scanner health, and metric
summaries. It calls the same FastAPI routes as the UI. It never mutates
findings.

Mint a personal token in the UI at `/settings/mcp`:

![Connect via MCP](../images/mcp-settings.png)

## Tools

| Tool | Backing route |
|---|---|
| `get_findings` | `GET /findings` |
| `get_sla_breaches` | `GET /findings` with critical/high and `sla_breached=true` |
| `get_scanner_health` | `GET /scanners/health` |
| `get_metrics_summary` | `GET /metrics/summary` plus `GET /metrics/trend` |

Filters on `get_findings` (`team`, `repo`, `asset`, `severity`, `status`,
`source`, `limit`) AND together. `repo` is an exact `repo:org/name` style
asset key; if you only know a substring, use `asset` instead. Admin-only
`sonarcloud_trivy` is hidden unless an admin passes that source explicitly.

## Local stdio (Cursor / Claude)

1. `make api-dev` (identity via `DEV_IDENTITY_EMAIL` in `.env.local`).
2. Point the MCP client at:

```bash
make mcp-dev
```

That is `python -m app.mcp.server` with `MCP_TRANSPORT` unset (stdio). The
server stamps `X-Dev-Identity` the same way the Next.js proxy does.

Example Cursor MCP config (adjust the repo path):

```json
{
  "mcpServers": {
    "secdb": {
      "command": "/Users/you/unified-security-dashboard-oss/backend/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "env": {
        "MCP_API_BASE_URL": "http://localhost:8000",
        "DEV_IDENTITY_EMAIL": "admin@example.com",
        "DEV_IDENTITY_GROUPS": "security@example.com"
      },
      "cwd": "/Users/you/unified-security-dashboard-oss/backend"
    }
  }
}
```

## Local streamable HTTP

```bash
make mcp-http-dev
```

Listens on http://127.0.0.1:3001 (override with `MCP_PORT`). Hosted mode
forwards `Authorization: Bearer` to the API; local stdio uses the dev
identity instead.

## Production

Cloud Run service behind the load balancer. Clients authenticate with a
personal token from **MCP** in the header (`/settings/mcp`):

1. Create a token. The `secdb_live_…` secret is shown once.
2. Send `Authorization: Bearer secdb_live_…` to `MCP_SERVER_URL`
   (typically `https://<hostname>/mcp`).
3. The MCP service calls the private API with workload identity and forwards
   the user's bearer token for RBAC (`is_admin` still comes from
   `rbac.yaml`).

Revoke tokens on the same settings page (`DELETE /me/tokens/{id}`).

`MCP_ACTIVE_ROLE` accepts only `admin` or `member` (default `admin` when
the user holds both historically). Legacy role names are rejected.
