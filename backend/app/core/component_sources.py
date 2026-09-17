"""Load view-mapping rows from repo config files (YAML + frontend TS constants).

Used only by config validation — runtime will move to component_registry.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.core.config_store import OwnershipMap


@dataclass(frozen=True)
class ComponentRow:
    """One service row from component-map.ts (MASTER_ROWS or PLATFORM_ENGINEERING_ROWS)."""

    service: str
    repo: str
    teams: tuple[str, ...]
    sonar_projects: tuple[str, ...]
    application_key: str
    source: str  # "master" | "platform_engineering" | "registry"


def _parse_string_list(raw: str) -> tuple[str, ...]:
    return tuple(re.findall(r'"([^"]+)"', raw))


def _extract_ts_array_body(text: str, array_name: str) -> str:
    """Slice the interior of `export const <name> = [ ... ];` without bracket-depth bugs."""
    marker = f"export const {array_name}"
    start = text.find(marker)
    if start < 0:
        raise ValueError(f"{array_name} not found in component-map.ts")
    open_bracket = text.index("[", start)
    boundaries = [
        text.find("\nexport const ", open_bracket + 1),
        text.find("\nconst ALL_", open_bracket + 1),
    ]
    next_boundary = min(b for b in boundaries if b >= 0)
    section = text[open_bracket:next_boundary]
    close = section.rindex("]")
    return section[1:close]


def _parse_ts_rows(text: str, array_name: str, *, source: str) -> list[ComponentRow]:
    body = _extract_ts_array_body(text, array_name)

    rows: list[ComponentRow] = []
    for chunk in re.split(r"\n  \},?\n", body):
        if "teams:" not in chunk or "repo:" not in chunk:
            continue
        teams_m = re.search(r"teams:\s*\[([^\]]*)\]", chunk, re.DOTALL)
        repo_m = re.search(r'repo:\s*"([^"]+)"', chunk)
        service_m = re.search(r'service:\s*"([^"]+)"', chunk)
        app_m = re.search(r'applicationKey:\s*"([^"]+)"', chunk)
        sonar_m = re.search(r"sonarProjects:\s*\[([\s\S]*?)\]", chunk)
        if not (teams_m and repo_m and service_m and app_m):
            continue
        sonar_raw = sonar_m.group(1) if sonar_m else ""
        rows.append(
            ComponentRow(
                service=service_m.group(1),
                repo=repo_m.group(1),
                teams=_parse_string_list(teams_m.group(1)),
                sonar_projects=_parse_string_list(sonar_raw),
                application_key=app_m.group(1),
                source=source,
            )
        )
    if not rows:
        raise ValueError(f"{array_name}: parsed zero rows from component-map.ts")
    return rows


def load_component_map_rows(repo_root: Path) -> list[ComponentRow]:
    path = repo_root / "frontend/app/lib/component-map.ts"
    text = path.read_text(encoding="utf-8")
    array_names = tuple(dict.fromkeys(re.findall(r"export const ([A-Z][A-Z0-9_]*_ROWS)\b", text)))
    if not array_names:
        raise ValueError("no exported component row arrays found in component-map.ts")
    rows: list[ComponentRow] = []
    for array_name in array_names:
        rows.extend(
            _parse_ts_rows(
                text,
                array_name,
                source=array_name.removesuffix("_ROWS").lower(),
            )
        )
    return rows


def load_exec_pillar_team_keys(repo_root: Path, pillar: str) -> tuple[str, ...]:
    path = repo_root / "frontend/app/lib/exec-pillars.ts"
    text = path.read_text(encoding="utf-8")
    pillar_m = re.search(
        rf'key:\s*"{re.escape(pillar)}"[\s\S]*?subTeams:\s*\[([\s\S]*?)\],\s*\}}',
        text,
    )
    if not pillar_m:
        raise ValueError(f"exec pillar {pillar!r} not found in exec-pillars.ts")
    keys = re.findall(r'teamKey:\s*"([^"]+)"', pillar_m.group(1))
    return tuple(keys)


def load_config_texts(config_dir: Path) -> tuple[str, str]:
    ownership = (config_dir / "ownership.yaml").read_text(encoding="utf-8")
    scope = (config_dir / "component_scope.yaml").read_text(encoding="utf-8")
    return ownership, scope


def load_registry_rows(config_dir: Path) -> list[dict] | None:
    path = config_dir / "component_registry.yaml"
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(raw.get("components") or [])


def repo_asset_id(
    repo: str,
    ownership: OwnershipMap,
    *,
    github_org: str | None = None,
) -> str:
    """Resolve a repo name without embedding an organization in application code."""
    suffix = f"/{repo}"
    matches = [
        asset_id
        for asset_id in ownership.asset_to_team
        if asset_id.startswith("repo:") and asset_id.endswith(suffix)
    ]
    if len(matches) == 1:
        return matches[0]

    org = get_settings().github_org if github_org is None else github_org
    org = org.strip()
    return f"repo:{org}/{repo}" if org else f"repo:{repo}"


def ingest_owner_for_row(
    row: ComponentRow,
    ownership: OwnershipMap,
    *,
    github_org: str | None = None,
) -> str:
    """Team stamped at ingest for this row's primary asset (Sonar key if set, else repo)."""
    if row.sonar_projects:
        for key in row.sonar_projects:
            asset_id = ownership.sonar_key_to_asset_id.get(key)
            if asset_id:
                return ownership.team_for_asset(asset_id)
            sonar_asset = f"sonarproj:{key}"
            if sonar_asset in ownership.asset_to_team:
                return ownership.team_for_asset(sonar_asset)
    if row.repo:
        return ownership.team_for_asset(
            repo_asset_id(row.repo, ownership, github_org=github_org)
        )
    return "unowned"
