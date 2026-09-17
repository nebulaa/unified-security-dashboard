#!/usr/bin/env python3
"""Validate the standalone OSS YAML configuration."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.component_registry import parse_component_registry  # noqa: E402
from app.core.component_sources import load_exec_pillar_team_keys  # noqa: E402
from app.core.config_store import _parse_ownership, _parse_scope_map  # noqa: E402
from app.core.config_validate import (  # noqa: E402
    ValidationResult,
    validate_ownership,
    validate_registry,
    validate_scope_map,
    validate_terraform_github_org,
    validate_wiz_service_catalog_live,
)
from app.core.wiz_subscription_pillar import (  # noqa: E402
    parse_wiz_subscription_pillar,
    validate_wiz_subscription_pillar_map,
)


def _merge(target: ValidationResult, source: ValidationResult) -> None:
    target.errors.extend(source.errors)
    target.warnings.extend(source.warnings)


def main() -> int:
    config = ROOT / "config"
    result = ValidationResult()

    ownership = _parse_ownership((config / "ownership.yaml").read_text())
    scope = _parse_scope_map((config / "component_scope.yaml").read_text())
    registry_text = (config / "component_registry.yaml").read_text()
    registry_raw = yaml.safe_load(registry_text) or {}

    for check in (
        validate_ownership(ownership),
        validate_scope_map(ownership, scope),
        validate_registry(ownership, registry_raw.get("components") or []),
        validate_terraform_github_org(ROOT / "deploy" / "terraform"),
        validate_wiz_service_catalog_live(registry_raw.get("components") or []),
    ):
        _merge(result, check)

    # Parse every runtime-owned mapping so schema regressions fail CI.
    parse_component_registry(registry_text)
    try:
        pillar_map = parse_wiz_subscription_pillar(
            (config / "wiz_subscription_pillar.yaml").read_text()
        )
        result.warnings.extend(validate_wiz_subscription_pillar_map(pillar_map))
    except ValueError as exc:
        result.errors.append(f"wiz_subscription_pillar.yaml: {exc}")

    registry_pillars = registry_raw.get("executive_pillars") or {}
    for pillar_key in ("product", "retail", "data"):
        try:
            exec_keys = load_exec_pillar_team_keys(ROOT, pillar_key)
        except (OSError, ValueError) as exc:
            result.errors.append(f"exec-pillars.ts: cannot load {pillar_key} pillar: {exc}")
            continue
        yaml_keys = tuple(
            str(t) for t in ((registry_pillars.get(pillar_key) or {}).get("team_keys") or [])
        )
        if sorted(yaml_keys) != sorted(exec_keys):
            result.errors.append(
                f"component_registry.yaml executive_pillars.{pillar_key}.team_keys "
                f"{list(yaml_keys)} != exec-pillars.ts {list(exec_keys)}"
            )

    ownership_teams = set(ownership.teams)
    supplemental = yaml.safe_load((config / "wiz_service_team_map.yaml").read_text()) or {}
    for service, team in (supplemental.get("teams") or {}).items():
        if team not in ownership_teams:
            result.errors.append(
                f"wiz_service_team_map.yaml: {service!r} references undefined team {team!r}"
            )

    for path in sorted(config.glob("*.yaml")):
        yaml.safe_load(path.read_text())

    for message in result.warnings:
        print(f"WARN: {message}")
    for message in result.errors:
        print(f"ERROR: {message}")

    if result.errors:
        print(f"FAILED: {len(result.errors)} error(s)")
        return 1
    print(f"OK: validated {len(list(config.glob('*.yaml')))} config files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
