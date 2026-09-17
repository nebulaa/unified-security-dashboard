"""`secdb wiz-map` — Wiz Service Catalog → component_registry (plans/wiz_auto_map.plan.md)."""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

from app.core.config_validate import default_paths
from app.core.db import session_scope
from app.core.wiz_auto_map import (
    apply_suggestions_to_registry,
    build_suggestions,
    load_overrides,
    load_registry_components,
    load_suggestions_from_yaml,
    load_wiz_service_team_map,
    load_wiz_slug_owner_teams,
    merge_suggest_yaml_with_existing,
    reresolve_wiz_owner_teams,
    suggest_to_yaml_dict,
    wiz_finding_counts,
    write_wiz_service_team_map,
)
from app.core.wiz_catalog import fetch_application_services_from_env, wiz_live_check_configured
from app.core.wiz_subscription_pillar import (
    reresolve_wiz_cloud_owner_teams,
    reresolve_wiz_platform_pillar_tags,
)


def _load_catalog(*, offline: bool):
    if offline:
        return []
    if not wiz_live_check_configured():
        click.echo(
            "WARN: WIZ_* not set — catalog inventory uses DB finding slugs only",
            err=True,
        )
        return []
    return fetch_application_services_from_env()


@click.group(help="Wiz Service Catalog → registry team mapping.")
def wiz_map() -> None:
    pass


@wiz_map.command("inventory")
@click.option("--offline", is_flag=True, help="Skip live Wiz API; use DB slugs only.")
def inventory(offline: bool) -> None:
    """Print catalog vs registry vs DB finding coverage."""
    config_dir, _ = default_paths()
    components = load_registry_components(config_dir)
    overrides = load_overrides(config_dir)

    with session_scope() as session:
        counts = wiz_finding_counts(session)

    try:
        catalog = _load_catalog(offline=offline)
    except Exception as exc:
        click.echo(f"ERROR: Wiz API: {exc}", err=True)
        sys.exit(1)

    report = build_suggestions(
        catalog=catalog,
        components=components,
        overrides=overrides,
        finding_counts=counts,
    )

    click.echo(f"Registry components: {len(components)}")
    click.echo(f"Already mapped wiz_service: {len(report.already_mapped)}")
    click.echo(f"Wiz catalog services: {len(catalog)}")
    click.echo(f"Distinct wizservice slugs in DB: {len(counts)}")
    click.echo(f"Pending suggestions (all confidence): {len(report.suggestions)}")
    click.echo(f"Unmapped catalog: {len(report.unmapped_catalog)}")
    click.echo(f"Unmapped DB-only slugs: {len(report.unmapped_findings_only)}")

    click.echo("\nTop DB slugs by finding count:")
    for slug, n in sorted(counts.items(), key=lambda x: -x[1])[:25]:
        mapped = next((k for s, k in report.already_mapped if s == slug), None)
        sug = next((s for s in report.suggestions if s.wiz_service == slug), None)
        status = "mapped" if mapped else (f"→ {sug.component_key}" if sug else "unmapped")
        click.echo(f"  {n:5d}  {slug:40s}  {status}")

    if report.conflicts:
        click.echo("\nConflicts:", err=True)
        for line in report.conflicts:
            click.echo(f"  {line}", err=True)


@wiz_map.command("suggest")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="Defaults to config/wiz_service_map.suggested.yaml",
)
@click.option("--offline", is_flag=True, help="Skip live Wiz API.")
@click.option(
    "--min-confidence",
    type=click.Choice(["high", "medium", "low"]),
    default=None,
    help="Filter suggestions written to output",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Exit 1 when conflicts remain (default: write file and exit 0)",
)
def suggest(
    output: Path | None,
    offline: bool,
    min_confidence: str | None,
    strict: bool,
) -> None:
    """Write wiz_service_map.suggested.yaml with scored mappings."""
    config_dir, _ = default_paths()
    out = output or (config_dir / "wiz_service_map.suggested.yaml")
    components = load_registry_components(config_dir)
    overrides = load_overrides(config_dir)

    with session_scope() as session:
        counts = wiz_finding_counts(session)

    catalog = _load_catalog(offline=offline)
    if not offline and not catalog and not counts:
        click.echo("ERROR: no catalog and no DB wiz findings", err=True)
        sys.exit(1)

    report = build_suggestions(
        catalog=catalog,
        components=components,
        overrides=overrides,
        finding_counts=counts,
        min_confidence=min_confidence,  # type: ignore[arg-type]
    )
    payload = suggest_to_yaml_dict(report)
    if out.is_file():
        payload = merge_suggest_yaml_with_existing(payload, out)
    out.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    click.echo(f"Wrote {out}")
    click.echo(
        f"{len(report.suggestions)} suggestion(s), "
        f"{len(report.conflicts)} skipped conflict(s), "
        f"{len(report.unmapped_catalog)} unmapped catalog slug(s)"
    )
    if report.conflicts:
        click.echo(
            "Conflicts are lower-priority matches; use wiz_service_overrides.yaml or "
            "re-run with --strict to fail CI.",
            err=True,
        )
        if strict:
            sys.exit(1)


@wiz_map.command("apply")
@click.option(
    "--from",
    "from_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Suggestions YAML (default: config/wiz_service_map.suggested.yaml)",
)
@click.option(
    "--min-confidence",
    type=click.Choice(["high", "medium", "low"]),
    default="high",
    show_default=True,
)
@click.option("--dry-run", is_flag=True)
def apply(from_path: Path | None, min_confidence: str, dry_run: bool) -> None:
    """Patch component_registry.yaml wiz_service fields from suggestions file."""
    config_dir, _ = default_paths()
    path = from_path or (config_dir / "wiz_service_map.suggested.yaml")
    if not path.is_file():
        click.echo(f"ERROR: missing {path}", err=True)
        sys.exit(1)
    suggestions, team_only = load_suggestions_from_yaml(path, config_dir=config_dir)
    updated, logs = apply_suggestions_to_registry(
        config_dir,
        suggestions,
        min_confidence=min_confidence,  # type: ignore[arg-type]
        dry_run=dry_run,
    )
    for line in logs:
        click.echo(line)
    click.echo(f"{'Would update' if dry_run else 'Updated'} {updated} registry row(s)")
    if team_only:
        merged = dict(load_wiz_service_team_map(config_dir))
        merged.update(team_only)
        write_wiz_service_team_map(config_dir, merged, dry_run=dry_run)
        click.echo(
            f"{'Would write' if dry_run else 'Wrote'} {len(team_only)} team-only slug(s) to "
            f"wiz_service_team_map.yaml ({len(merged)} total)"
        )


@wiz_map.command("reresolve")
@click.option("--dry-run", is_flag=True, help="Report counts without writing.")
def reresolve(dry_run: bool) -> None:
    """Re-stamp owner_team on open Wiz findings (wizservice:* + cloudres:*)."""
    config_dir, _ = default_paths()
    try:
        mapping = load_wiz_slug_owner_teams(config_dir)
    except ValueError as exc:
        click.echo(f"ERROR: registry: {exc}", err=True)
        sys.exit(1)
    with session_scope() as session:
        svc_scanned, svc_updated = reresolve_wiz_owner_teams(
            session, mapping, dry_run=dry_run
        )
        cloud_scanned, cloud_updated = reresolve_wiz_cloud_owner_teams(
            session, dry_run=dry_run
        )
    click.echo(
        f"{'Would update' if dry_run else 'Updated'} {svc_updated} / {svc_scanned} "
        f"open wizservice findings ({len(mapping)} registry wiz_service slugs)"
    )
    click.echo(
        f"{'Would update' if dry_run else 'Updated'} {cloud_updated} / {cloud_scanned} "
        f"open cloudres findings (platform_pillar:* → platform code team)"
    )


@wiz_map.command("reresolve-pillar")
@click.option("--dry-run", is_flag=True, help="Report counts without writing.")
def reresolve_pillar(dry_run: bool) -> None:
    """Re-stamp platform_pillar:* tags on open Wiz findings from cloud_account tags."""
    from app.core.config_store import get_config_cache

    pillar_map = get_config_cache().get_wiz_subscription_pillar()
    with session_scope() as session:
        scanned, updated = reresolve_wiz_platform_pillar_tags(
            session, pillar_map, dry_run=dry_run
        )
    click.echo(
        f"{'Would update' if dry_run else 'Updated'} {updated} / {scanned} "
        f"open Wiz findings (subscription pillar map)"
    )
