"""Cross-file config consistency checks — CI / pre-deploy gate.

Fails closed when ownership, component_scope.yaml, and frontend view maps disagree.
See plans/component_registry_consolidation.plan.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.component_sources import (
    ComponentRow,
    ingest_owner_for_row,
    load_component_map_rows,
    load_config_texts,
    load_registry_rows,
)
from app.core.config_store import OwnershipMap, ScopeMap, _parse_ownership, _parse_scope_map
from app.core.wiz_catalog import (
    fetch_wiz_application_service_names_from_env,
    wiz_live_check_configured,
)

# `variable "github_org" { ... default = "..." ... }` — DOTALL so the block
# body (which spans multiple lines) is captured. Anchored on the variable
# *name* so we only match the github_org block, not other variables.
_TF_GITHUB_ORG_VAR_RE = re.compile(
    r'variable\s+"github_org"\s*\{[^}]*?default\s*=\s*"([^"]*)"',
    re.DOTALL,
)
# `github_org = "..."` at the start of a line in a tfvars file.
_TFVARS_GITHUB_ORG_RE = re.compile(
    r'^\s*github_org\s*=\s*"([^"]*)"',
    re.MULTILINE,
)


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


def validate_ownership(ownership: OwnershipMap) -> ValidationResult:
    result = ValidationResult()

    referenced_teams = set(ownership.asset_to_team.values())
    defined_teams = set(ownership.teams.keys())
    missing_teams = referenced_teams - defined_teams - {"unowned", "excluded"}
    if missing_teams:
        result.error(
            f"ownership.yaml: {len(missing_teams)} team(s) on assets but not in teams: "
            f"{sorted(missing_teams)}"
        )

    defined_pillars = set(ownership.pillars.keys())
    for name, cfg in ownership.teams.items():
        if cfg.pillar and cfg.pillar not in defined_pillars:
            result.error(
                f"ownership.yaml: team {name!r} references undefined pillar {cfg.pillar!r}"
            )

    for repo in sorted(ownership.excluded_repos):
        matching_assets = [
            asset_id
            for asset_id in ownership.asset_to_team
            if asset_id.startswith("repo:") and asset_id.endswith(f"/{repo}")
        ]
        if matching_assets:
            result.error(
                f"ownership.yaml: excluded repo {repo!r} is also listed in assets[] "
                f"(asset={matching_assets[0]}, team={ownership.asset_to_team[matching_assets[0]]})"
            )

    return result


def _collect_scope_team_keys(scope: ScopeMap) -> set[str]:
    keys: set[str] = set()
    for teams in scope.executive_pillar_to_teams.values():
        keys.update(teams)
    for teams in scope.application_to_teams.values():
        keys.update(teams)
    for teams in scope.service_to_teams.values():
        keys.update(teams)
    return keys


def validate_scope_map(ownership: OwnershipMap, scope: ScopeMap) -> ValidationResult:
    result = ValidationResult()
    defined = set(ownership.teams.keys())

    for team in sorted(_collect_scope_team_keys(scope) - defined):
        result.error(f"component_scope.yaml: team {team!r} is not defined in ownership.yaml")

    return result


def validate_component_rows(
    ownership: OwnershipMap,
    rows: list[ComponentRow],
    *,
    label: str,
) -> ValidationResult:
    result = ValidationResult()
    defined = set(ownership.teams.keys())

    for row in rows:
        if not row.teams:
            result.error(f"{label}: service {row.service!r} has no teams")
            continue

        primary = row.teams[0]
        for team in row.teams:
            if team not in defined:
                result.error(
                    f"{label}: service {row.service!r} references undefined team {team!r}"
                )

        stamped = ingest_owner_for_row(row, ownership)
        if stamped in ("unowned", "excluded"):
            result.error(
                f"{label}: service {row.service!r} (repo={row.repo!r}) has no ownership "
                f"asset for ingest (stamped {stamped!r})"
            )
        elif primary != stamped:
            result.error(
                f"{label}: service {row.service!r} teams[0]={primary!r} but ingest stamps "
                f"{stamped!r} for repo/sonar asset — align component map with ownership.yaml "
                f"(or reorder teams[] so [0] matches ingest)"
            )

    return result


def validate_scope_service_rows(
    rows: list[ComponentRow],
    scope: ScopeMap,
) -> ValidationResult:
    """component_scope.services[].teams[0] must match the TS row for that service key."""
    result = ValidationResult()
    by_service_key: dict[str, ComponentRow] = {}
    for row in rows:
        norm = re.sub(r"[^a-z0-9]", "", row.service.lower())
        by_service_key[norm] = row

    for svc_key, teams in scope.service_to_teams.items():
        if not teams:
            continue
        norm = re.sub(r"[^a-z0-9]", "", svc_key.lower())
        row = by_service_key.get(norm)
        if row is None:
            result.warn(
                f"component_scope.yaml: service {svc_key!r} has no matching "
                f"component-map.ts row (scope partial or rename drift)"
            )
            continue
        if teams[0] != row.teams[0]:
            result.error(
                f"component_scope.yaml: services.{svc_key}.teams[0]={teams[0]!r} but "
                f"component-map {row.service!r} teams[0]={row.teams[0]!r}"
            )
    return result


_VALID_VIEWS = frozenset({"developer", "executive", "platform"})


def validate_registry(
    ownership: OwnershipMap,
    registry_components: list[dict],
) -> ValidationResult:
    result = ValidationResult()
    defined = set(ownership.teams.keys())
    seen_keys: set[str] = set()
    seen_wiz: dict[str, str] = {}

    for raw in registry_components:
        key = str(raw.get("key") or "")
        if not key:
            result.error("component_registry.yaml: component row missing key")
            continue
        if key in seen_keys:
            result.error(f"component_registry.yaml: duplicate component key {key!r}")
        seen_keys.add(key)

        teams = [str(t) for t in (raw.get("teams") or [])]
        repo = str(raw.get("repo") or "").strip() or None
        sonar = [str(s) for s in (raw.get("sonar_projects") or [])]
        wiz = str(raw.get("wiz_service") or "").strip() or None
        views = [str(v) for v in (raw.get("views") or [])]

        if not teams:
            result.error(f"component_registry.yaml: {key!r} missing teams")
            continue
        if not repo and not sonar and not wiz:
            result.error(
                f"component_registry.yaml: {key!r} must have at least one of "
                f"repo, sonar_projects, wiz_service"
            )
            continue
        for view in views:
            if view not in _VALID_VIEWS:
                result.error(
                    f"component_registry.yaml: {key!r} invalid views value {view!r}"
                )
        if wiz:
            if wiz in seen_wiz:
                result.error(
                    f"component_registry.yaml: duplicate wiz_service {wiz!r} on "
                    f"{seen_wiz[wiz]!r} and {key!r}"
                )
            seen_wiz[wiz] = key

        row = ComponentRow(
            service=str(raw.get("label") or key),
            repo=repo or "",
            teams=tuple(teams),
            sonar_projects=tuple(sonar),
            application_key=str(raw.get("application") or ""),
            source="registry",
        )
        for team in teams:
            if team not in defined:
                result.error(
                    f"component_registry.yaml: {key!r} references undefined team {team!r}"
                )

        if repo or sonar:
            stamped = ingest_owner_for_row(row, ownership)
            if stamped in ("unowned", "excluded"):
                result.error(
                    f"component_registry.yaml: {key!r} has no ownership asset "
                    f"(stamped {stamped!r})"
                )
            elif teams[0] != stamped:
                result.error(
                    f"component_registry.yaml: {key!r} teams[0]={teams[0]!r} but ingest "
                    f"stamps {stamped!r}"
                )

    return result


def _parse_tf_github_org_default(variables_tf_text: str) -> str | None:
    """Return the `default` value of `variable "github_org"` from variables.tf,
    or `None` if the variable is missing or has no default. An explicit
    `default = ""` returns the empty string (not None) so the caller can
    distinguish "no default at all" from "default set to empty"."""
    match = _TF_GITHUB_ORG_VAR_RE.search(variables_tf_text)
    return match.group(1) if match else None


def _parse_tfvars_github_org_override(tfvars_text: str) -> str | None:
    """Return the value the tfvars file assigns to `github_org`, or `None`
    if it doesn't override the variable. As above: `""` is a valid value
    that's distinguishable from `None`."""
    match = _TFVARS_GITHUB_ORG_RE.search(tfvars_text)
    return match.group(1) if match else None


def validate_terraform_github_org(tf_dir: Path) -> ValidationResult:
    """Fail closed when any Terraform var-file resolves `github_org` to empty.

    Why this is load-bearing: SonarCloud findings get their canonical
    `repo:<github_org>/<name>` asset_id from `settings.github_org` (see
    `_resolve_asset_id` in the SonarCloud mapper). An empty value lands the
    convention path on the project-key escape valve (`repo:{project_key}`),
    so every Sonar finding lands `unowned` on /admin and the cloud rolls
    them off /executive. The mapper now refuses to silently fall back to
    `organization` (lowercase Sonar org), which prevents the *masquerade*
    failure mode that produced the `example-service` see-saw — but a deploy
    with empty `GITHUB_ORG` would still leave the entire SonarCloud-
    sourced surface unowned. Catching this in pre-merge CI prevents the
    misconfig from reaching prod.

    Resolution rule per env tfvars: effective value =
    `tfvars override` if set (including `""`), else
    `default` from `variable "github_org" { default = ... }` in
    `variables.tf`. Fail when effective is empty or absent.
    """
    result = ValidationResult()

    variables_tf = tf_dir / "variables.tf"
    if not variables_tf.exists():
        # Not a Terraform-managed tree — likely a `make validate-config`
        # invoked from a fork or outside the deploy layout. Skip silently
        # rather than erroring, so the YAML cross-checks still run.
        return result

    default = _parse_tf_github_org_default(variables_tf.read_text(encoding="utf-8"))
    tfvars_files = sorted(tf_dir.glob("*.tfvars"))

    if not tfvars_files:
        # No env tfvars — single-deploy mode. The default alone must be
        # non-empty.
        if not default:
            result.error(
                "deploy/terraform/variables.tf: variable \"github_org\" has no "
                "non-empty default and no tfvars override exists. An empty "
                "GITHUB_ORG produces lowercase repo:<org>/... asset_ids that "
                "can't match ownership.yaml — every SonarCloud finding would "
                "land unowned."
            )
        return result

    for tfvars in tfvars_files:
        override = _parse_tfvars_github_org_override(
            tfvars.read_text(encoding="utf-8")
        )
        # `override is None` => use default; `override == ""` => explicitly empty.
        effective = override if override is not None else default
        if not effective:
            label = f"deploy/terraform/{tfvars.name}"
            if override == "":
                result.error(
                    f"{label}: github_org is set to empty string. An empty "
                    f"GITHUB_ORG produces lowercase repo:<org>/... asset_ids "
                    f"that can't match ownership.yaml — every SonarCloud "
                    f"finding would land unowned in this environment."
                )
            else:
                result.error(
                    f"{label}: github_org has no override and "
                    f"variable \"github_org\" in variables.tf has no "
                    f"non-empty default. Set one or the other."
                )

    return result


def _registry_wiz_services(registry_components: list[dict]) -> set[str]:
    slugs: set[str] = set()
    for raw in registry_components:
        wiz = str(raw.get("wiz_service") or "").strip()
        if wiz:
            slugs.add(wiz)
    return slugs


def validate_wiz_service_catalog_live(
    registry_components: list[dict],
) -> ValidationResult:
    """Warn when registry `wiz_service:` slugs drift from the live Wiz tenant."""
    result = ValidationResult()
    registry_slugs = _registry_wiz_services(registry_components)
    if not registry_slugs:
        return result
    if not wiz_live_check_configured():
        result.warn(
            "wiz catalog: skipped live check (set WIZ_API_URL, WIZ_CLIENT_ID, "
            "WIZ_CLIENT_SECRET to validate wiz_service slugs against Wiz)"
        )
        return result
    try:
        live = fetch_wiz_application_service_names_from_env()
    except Exception as exc:
        result.warn(f"wiz catalog: live check failed ({exc})")
        return result

    missing = sorted(registry_slugs - live)
    for slug in missing:
        result.warn(
            f"component_registry.yaml: wiz_service {slug!r} not in Wiz Service "
            f"Catalog (findings will land unowned until slug exists or row is fixed)"
        )

    unmapped = sorted(live - registry_slugs)
    if unmapped:
        sample = ", ".join(unmapped[:8])
        suffix = f" (+{len(unmapped) - 8} more)" if len(unmapped) > 8 else ""
        result.warn(
            f"wiz catalog: {len(unmapped)} Wiz Service Catalog entr(y/ies) have no "
            f"component_registry.yaml row (e.g. {sample}{suffix}) — "
            f"findings on those services land unowned"
        )
    return result


def validate_all(
    *,
    config_dir: Path,
    repo_root: Path,
) -> ValidationResult:
    ownership_text, scope_text = load_config_texts(config_dir)
    ownership = _parse_ownership(ownership_text)
    scope = _parse_scope_map(scope_text)

    combined = ValidationResult()
    for part in (
        validate_ownership(ownership),
        validate_scope_map(ownership, scope),
        validate_terraform_github_org(repo_root / "deploy" / "terraform"),
    ):
        combined.errors.extend(part.errors)
        combined.warnings.extend(part.warnings)

    registry = load_registry_rows(config_dir)
    if registry is not None:
        part = validate_registry(ownership, registry)
        combined.errors.extend(part.errors)
        combined.warnings.extend(part.warnings)
        part = validate_wiz_service_catalog_live(registry)
        combined.errors.extend(part.errors)
        combined.warnings.extend(part.warnings)
    else:
        combined.warn(
            "component_registry.yaml not found — using component-map.ts for validation only"
        )
        try:
            rows = load_component_map_rows(repo_root)
        except (OSError, ValueError) as exc:
            combined.error(f"component-map.ts: cannot load rows: {exc}")
            rows = []
        if rows:
            for part in (
                validate_component_rows(ownership, rows, label="component-map.ts"),
                validate_scope_service_rows(rows, scope),
            ):
                combined.errors.extend(part.errors)
                combined.warnings.extend(part.warnings)

    pillar_path = config_dir / "wiz_subscription_pillar.yaml"
    if pillar_path.is_file():
        from app.core.wiz_subscription_pillar import (
            parse_wiz_subscription_pillar,
            validate_wiz_subscription_pillar_map,
        )

        try:
            pillar_map = parse_wiz_subscription_pillar(
                pillar_path.read_text(encoding="utf-8")
            )
            for err in validate_wiz_subscription_pillar_map(pillar_map):
                combined.warn(err)
        except ValueError as exc:
            combined.error(f"wiz_subscription_pillar.yaml: {exc}")
    return combined


def default_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[3]
    config_dir = repo_root / "config"
    return config_dir, repo_root
