# Ingest and finding lifecycle

Pollers collect a full snapshot from one scanner, persist the raw payload,
and tell the normalizer to process it. The normalizer is idempotent: the same
`(source, poll_id)` is applied at most once.

## Pollers

| Make target | Module | Typical source values on findings |
|---|---|---|
| `make poller-dependabot` | `app.pollers.dependabot` | `dependabot` |
| `make poller-sonarcloud` | `app.pollers.sonarcloud` | `sonarcloud`, `sonarcloud_trivy` |
| `make poller-wiz` | `app.pollers.wiz` | `wiz` |
| `make poller-jira-pentest` | `app.pollers.jira_pentest` | `pentest` |

Each poller writes the snapshot to `RAW_STORE` (`fs` locally, `gcs` in GCP)
and publishes `{source, poll_id, raw_uri}` over `INGEST_TRANSPORT`.

Admins can also trigger the same jobs from `/admin` (`POST /admin/pollers/{source}/run`).
Locally that runs the poller in-process; in GCP it starts the Cloud Run job.

First Wiz load often needs a wider window: `make poller-wiz-backfill`.

## Normalizer

`POST /internal/normalize` loads the raw snapshot, selects a mapper, and
calls `process_snapshot()` inside one database transaction
(`backend/app/normalizer/processor.py`):

1. Insert `processed_payloads(source, poll_id)`. Conflict means already done.
2. Upsert every finding in the snapshot:
   - new → insert, event `discovered`
   - previously `auto_closed` and present again → `open`, event `reopened`
   - field changes → typed events (`severity_changed`, …)
   - always refresh `last_seen_at` and reset `consecutive_misses`
3. Open findings from the same source group that are absent: increment
   `consecutive_misses`.
4. Cross the `auto_close.yaml` threshold → status `auto_closed`.

Finding identity is deterministic: `id = uuid5(source + native_id)`.
`owner_team` is stamped from the ownership map at ingest (`unowned` if the
asset is unknown). A change in resolved team emits `ownership_changed`.

SonarCloud native issues and Sonar-hosted Trivy issues share one snapshot
group so absence and auto-close stay in sync.

## Statuses

Open: `open`, `triaged`, `in_progress`.

Closed: `fixed`, `auto_closed`, `risk_accepted`, `suppressed`.

SLA clocks use severity windows from `sla.yaml` and are evaluated at read
time, not stored on the row.

## Jobs after ingest

- **Daily metrics** (`app.jobs.rollup`): buckets by team, source, and
  severity for trend charts. Local: `make rollup-backfill`. GCP: Cloud Run
  job `secdb-rollup`.
- **Ownership re-resolve** (`app.jobs.ownership_reresolve`): re-stamps
  `owner_team` after YAML edits without waiting for the next poll. Local:
  `make ownership-reresolve`. Preview: `make ownership-reresolve-dry-run`.
- **Wiz mapping CLI**: `make wiz-map-inventory`, `wiz-map-suggest`,
  `wiz-map-apply`, `wiz-map-reresolve` when catalog slugs drift from the
  registry.

## Failures

When Pub/Sub ingest fails, messages land on the DLQ. The normalizer
`POST /internal/dlq` records them. Admins see and resolve events on `/admin`.
Optional Slack: `SLACK_WEBHOOK_URL`.
