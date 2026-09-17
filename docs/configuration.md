# Configuration

Runtime policy lives in YAML under `config/`. The API, normalizer, CLI, and
config validator all read the same files. In GCP, Terraform uploads them to
the config bucket; locally they are read from `CONFIG_STORE_FS_ROOT`
(default `./config`).

Replace the fictional ExampleOrg values before a real deployment. Keep team
keys identical across ownership, registry, scope, and Wiz maps. After every
edit:

```bash
make validate-config
```

Hot-reload in a running process: `POST /internal/config-reload` on the API
and normalizer (OIDC in production). Ownership already stored on findings is
not rewritten until the next ingest or `make ownership-reresolve`.

## Files

### `ownership.yaml`

Pillars, teams, members, excluded repos, and scanner assets. Asset ids look
like `repo:ExampleOrg/web-store` or `sonarproj:ExampleOrg_web-store`. Each
asset maps to a team key. Findings whose asset is missing land on
`owner_team=unowned`.

### `component_registry.yaml`

Canonical components: repo, Sonar projects, Wiz service slug, owning teams,
application grouping, and which dashboard views (`developer`, `platform`,
`executive`) show the component. `executive_pillars` here drives executive
rollups.

### `component_scope.yaml`

Compact executive / application / service map used by scope helpers and
validation. Team keys must exist in `ownership.yaml`.

### `rbac.yaml`

```yaml
admin_emails:
  - admin@example.com
```

That list is the only admin grant. IAP (production) or `DEV_IDENTITY_EMAIL`
(local) decides who can hit the app at all.

### `sla.yaml`

Remediation windows per severity, computed at read time, never stored:

```yaml
sla:
  critical: 7d
  high: 30d
  medium: 90d
  low: 180d
  info: null
```

### `auto_close.yaml`

How many consecutive missed snapshots it takes to mark an open finding
`auto_closed`. `null` means never. SonarCloud uses a higher threshold because
multi-org polls publish one snapshot per org.

### `coverage.yaml`

Inventory denominator, green/amber thresholds, enabled layers (local demo is
`code` only), GitHub eligibility, and named coverage projects.

### `jira_pentest.yaml`

Optional Jira project, open-issue JQL, severity custom field, and `team:`
label prefix used by the pentest poller.

### Wiz helpers

- `wiz_service_team_map.yaml` — Wiz service → team when the registry has no
  `wiz_service` slug.
- `wiz_subscription_pillar.yaml` — cloud subscription → executive pillar.
- `wiz_service_overrides.yaml.example` — copy to overrides when you need
  manual catalog exceptions.

## Alignment rules the validator enforces

`scripts/validate_config.py` (via `make validate-config` or `make cli ARGS="config validate"`):

- Every team key in scope and registry exists in ownership.
- Pillars referenced by teams exist.
- Registry components parse cleanly.
- Optional live Wiz catalog check when credentials are present.
- Terraform GitHub org settings stay consistent when those files exist.

Frontend view maps (`frontend/app/lib/component-map.ts`,
`exec-pillars.ts`) must stay aligned with the YAML; the validator is the
pre-merge gate.

## What YAML does not do

- It does not grant dashboard login. Production login is IAP
  (`iap_members` in Terraform). Local login is whoever you stamp in
  `DEV_IDENTITY_EMAIL`.
- It does not store findings. Those come from pollers.
- Editing `admin_emails` does not require a database migration; reload or
  restart the API.
