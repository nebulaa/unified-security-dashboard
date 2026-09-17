# Documentation

This folder explains how the Unified Security Dashboard is put together and how
to run, configure, and operate it. The committed ExampleOrg YAML is fictional
and is safe to use as a local demo.

| Document | What it covers |
|---|---|
| [Architecture](architecture.md) | Services, data flow, identity, and repository layout |
| [Local development](dev-setup.md) | Bootstrapping Postgres, API, normalizer, and frontend |
| [Configuration](configuration.md) | YAML ownership, scope, RBAC, SLA, coverage, and Wiz maps |
| [Ingest](ingest.md) | Pollers, snapshots, ownership stamping, auto-close, rollups |
| [Frontend](frontend.md) | Views, screenshots, identity, and theming |
| [HTTP API](api.md) | FastAPI routes used by the UI and MCP |
| [CLI](cli.md) | Operator commands for attribution gaps and scanner status |
| [MCP server](user/mcp-server.md) | Read-only agent access to findings and metrics |
| [GCP Terraform](../deploy/terraform/README.md) | Cloud Run, Cloud SQL, IAP, and first-time apply |

Related root files: [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md),
[SECURITY](../SECURITY.md).
