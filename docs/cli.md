# CLI

Operator tool for attribution gaps and scanner health. It is not a user
directory: access is IAP + `rbac.yaml`, and MCP tokens are created in the UI.

```bash
make cli ARGS="--help"
make cli ARGS="ownership validate"
make cli ARGS="config validate"
make cli ARGS="findings unowned"
make cli ARGS="scanner status"
```

Equivalent: `cd backend && ../backend/.venv/bin/python -m app.cli.main …`
after `LOAD_ENV` from `.env.local` (the Makefile does that for you).

## Commands

### `ownership validate`

Lint `ownership.yaml`. Undefined pillars or teams fail. Missing
engineering manager or security PoC contacts are informational.

### `config validate`

Same cross-file checks as `make validate-config`: ownership, scope,
registry, optional Wiz catalog, Terraform GitHub org consistency.

### `findings unowned`

Open findings with `owner_team=unowned`. Fix by adding the asset to
`ownership.yaml` (or Wiz maps), then ingest or `make ownership-reresolve`.

### `scanner status`

Last processed snapshot time, poll count, and finding count per source.
Terminal counterpart to `GET /scanners/health`.

### Wiz mapping

```bash
make wiz-map-inventory
make wiz-map-suggest
make wiz-map-apply
make wiz-map-reresolve
make wiz-map-reresolve-pillar
```

These wrap `python -m app.cli.main wiz-map …`. Use them when Wiz service
slugs are missing from `component_registry.yaml`. Live catalog calls need
`WIZ_*` in `.env.local`.
