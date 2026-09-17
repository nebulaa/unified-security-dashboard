"""`secdb` CLI — operator gap-triage tool (design §8).

Purpose
-------
The CLI exists to close the *coverage gap*: surfacing findings the dashboard
ingested but cannot attribute, so an admin can fix the responsible config
(`ownership.yaml`, `dev-view mapping.md`) and redeploy. It is **not** a user-
management tool — see "What this CLI is no longer for" below.

All operations read/write the same SQLAlchemy session as the API. Auth is
GCP ADC in production; local dev uses the configured DATABASE_URL directly.

Subcommand groups
-----------------
    ownership   validate    Lint ownership.yaml — fatal on undefined pillars/
                            teams (CI pre-merge gate);
                            informational on missing engineering_manager /
                            security_poc contacts.

    config      validate    Cross-check ownership.yaml, component_scope.yaml,
                            and frontend view maps (component-map.ts,
                            exec-pillars.ts). Fails closed in CI before deploy.

    findings    unowned     List open findings whose asset is not in
                            ownership.yaml (owner_team = "unowned"). Primary
                            queue for closing attribution gaps — resolution is
                            always "add the asset to ownership.yaml and
                            redeploy".

    scanner     status      Show last `processed_payloads.processed_at`, poll
                            count, and finding count per known source.
                            Terminal counterpart to GET /scanners/health.

    backfill                Seed historical findings + events for 30/90d
                            rolling metrics. Prototype: stub.

What this CLI is no longer for
-------------------------------
The `roles {grant,revoke,list}` subcommand group was removed
when the role hierarchy collapsed.
Granting dashboard access is not a CLI operation anymore:

* Every signed-in member of `engineering@example.com` is allowed onto every
  dashboard surface except `/admin` — enforced by IAP at the load balancer.
* The single admin grant lives in `config/rbac.yaml.admin_emails` and is a
  YAML edit + Terraform apply, not a database write.
* The `role_overrides` table is retained for historical migrations only;
  the API does not read it any more (see `app/core/rbac.py`).

Issuing personal MCP tokens is also out of scope here — that moved to the
self-service `/settings/mcp` UI.
"""

from __future__ import annotations

import sys

import click
from sqlalchemy import func, select

from app.core.component_sources import load_config_texts
from app.core.config_store import _parse_ownership
from app.core.config_validate import default_paths, validate_all, validate_ownership
from app.core.db import session_scope
from app.core.enums import KNOWN_SOURCES, Status
from app.core.models import Finding, ProcessedPayload


@click.group(help="Unified Security Dashboard admin CLI.")
def cli() -> None:
    pass


# ---------------- ownership ----------------


@cli.group(help="Operations on ownership.yaml.")
def ownership() -> None:
    pass


@ownership.command("validate")
def ownership_validate() -> None:
    """Lint ownership.yaml (subset of `secdb config validate`)."""
    config_dir, _repo_root = default_paths()
    ownership_text, _scope_text = load_config_texts(config_dir)
    result = validate_ownership(_parse_ownership(ownership_text))
    for msg in result.errors:
        click.echo(f"ERROR: {msg}", err=True)
    if result.errors:
        sys.exit(1)
    click.echo("OK")


@cli.group(help="Cross-file config consistency (CI gate).")
def config() -> None:
    pass


@config.command("validate")
def config_validate() -> None:
    """Fail if ownership, component_scope, and view maps disagree."""
    config_dir, repo_root = default_paths()
    result = validate_all(config_dir=config_dir, repo_root=repo_root)

    for msg in result.warnings:
        click.echo(f"WARN: {msg}", err=True)
    for msg in result.errors:
        click.echo(f"ERROR: {msg}", err=True)

    if result.errors:
        click.echo(f"\n{len(result.errors)} error(s) — fix config before deploy.", err=True)
        sys.exit(1)
    if result.warnings:
        click.echo(f"OK ({len(result.warnings)} warning(s))")
    else:
        click.echo("OK")


# ---------------- scanner ----------------


@cli.group(help="Scanner ingest health.")
def scanner() -> None:
    pass


@scanner.command("status")
def scanner_status() -> None:
    """Show last `processed_payloads.processed_at` per source, plus poll count."""
    with session_scope() as s:
        rows = s.execute(
            select(
                ProcessedPayload.source,
                func.max(ProcessedPayload.processed_at),
                func.count(),
                func.sum(ProcessedPayload.finding_count),
            ).group_by(ProcessedPayload.source)
        ).all()

        seen_by_source: dict[str, tuple] = {row[0]: row for row in rows}

    click.echo(f"{'source':15s} {'last_seen':32s} {'polls':>7s} {'findings':>10s}")
    for source in sorted(KNOWN_SOURCES):
        if source in seen_by_source:
            _, last_seen, count, total_findings = seen_by_source[source]
            click.echo(
                f"{source:15s} {str(last_seen):32s} {count:>7d} {int(total_findings or 0):>10d}"
            )
        else:
            click.echo(f"{source:15s} {'(no data)':32s} {0:>7d} {0:>10d}")


# ---------------- findings ----------------


@cli.group(help="Finding queries (admin-side).")
def findings() -> None:
    pass


@findings.command("unowned")
def findings_unowned() -> None:
    """List findings whose asset is not in ownership.yaml (D15)."""
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(Finding)
                .where(
                    Finding.owner_team == "unowned",
                    Finding.status.in_([st.value for st in Status.open_set()]),
                )
                .order_by(Finding.severity, Finding.first_seen_at)
            )
        )
    if not rows:
        click.echo("no unowned open findings")
        return
    click.echo(f"{len(rows)} unowned open findings:")
    for f in rows:
        click.echo(
            f"  {f.source:12s} {f.severity.value:8s} {f.asset_display:40s} {f.title[:60]}"
        )


# ---------------- backfill ----------------


@cli.command(
    help=(
        "Seed historical findings + events for rolling 30/90d metrics.",
    ),
)
@click.option("--source", required=True, type=click.Choice(["dependabot", "sonarcloud"]))
@click.option("--days", type=int, default=90, show_default=True)
@click.option("--dry-run", is_flag=True, help="Fetch and report counts only (not implemented).")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt (not implemented).")
def backfill(source: str, days: int, dry_run: bool, yes: bool) -> None:
    del dry_run, yes  # wired when Tier 1 lands
    click.echo(
        f"backfill {source} ({days}d): not implemented",
        err=True,
    )
    sys.exit(2)


def main() -> None:
    from app.cli.wiz_map import wiz_map

    cli.add_command(wiz_map)
    cli()


if __name__ == "__main__":
    main()
