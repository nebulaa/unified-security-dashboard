"""Component Registry — view mapping loaded from `component_registry.yaml`."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from app.core.config_store import OwnershipMap


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


@dataclass(frozen=True)
class ExecutiveSubTeam:
    label: str
    team_key: str | None


@dataclass(frozen=True)
class ExecutivePillar:
    key: str
    label: str
    team_keys: tuple[str, ...]
    sub_teams: tuple[ExecutiveSubTeam, ...]


@dataclass(frozen=True)
class ComponentEntry:
    key: str
    label: str
    application: str
    application_label: str
    teams: tuple[str, ...]
    views: frozenset[str]
    dev_pillar: str | None = None
    repo: str | None = None
    sonar_projects: tuple[str, ...] = ()
    wiz_service: str | None = None


@dataclass(frozen=True)
class ApplicationIndex:
    key: str
    label: str
    services: tuple[str, ...]
    repos: tuple[str, ...]
    teams: tuple[str, ...]
    dev_pillar: str | None


@dataclass(frozen=True)
class ComponentRegistry:
    version: int
    components: tuple[ComponentEntry, ...]
    executive_pillars: tuple[ExecutivePillar, ...]
    out_of_view_teams: frozenset[str]
    # Derived indexes (not in YAML)
    application_to_teams: dict[str, tuple[str, ...]] = field(default_factory=dict)
    application_to_repos: dict[str, tuple[str, ...]] = field(default_factory=dict)
    applications: tuple[ApplicationIndex, ...] = ()
    component_by_key: dict[str, ComponentEntry] = field(default_factory=dict)
    wiz_service_to_team: dict[str, str] = field(default_factory=dict)
    wiz_teams_for_pillar: dict[str, frozenset[str]] = field(default_factory=dict)
    developer_scope_team_keys: tuple[str, ...] = ()
    loaded_at: float = 0.0

    def teams_for_executive_pillar(self, key: str) -> tuple[str, ...]:
        norm = key.lower()
        for pillar in self.executive_pillars:
            if pillar.key.lower() == norm:
                return pillar.team_keys
        return ()

    def teams_for_application(self, key: str) -> tuple[str, ...]:
        return self.application_to_teams.get(key.lower(), ())

    def repos_for_application(self, key: str) -> tuple[str, ...]:
        return self.application_to_repos.get(key.lower(), ())

    def repo_asset_ids_for_application(
        self, key: str, ownership: OwnershipMap
    ) -> tuple[str, ...]:
        """Resolve registry repo + sonar keys to canonical `Finding.asset_id` values."""
        from app.core.component_sources import repo_asset_id

        app_key = key.lower()
        asset_ids: list[str] = []
        for comp in self.components:
            if comp.application.lower() != app_key:
                continue
            if comp.repo:
                suffix = f"/{comp.repo}"
                matches = [
                    aid
                    for aid in ownership.asset_to_team
                    if aid.startswith("repo:") and aid.endswith(suffix)
                ]
                if len(matches) == 1:
                    asset_ids.append(matches[0])
                else:
                    asset_ids.append(repo_asset_id(comp.repo, ownership))
            for sp in comp.sonar_projects:
                mapped = ownership.sonar_key_to_asset_id.get(sp)
                if mapped:
                    asset_ids.append(mapped)
                sonar_asset = f"sonarproj:{sp}"
                if sonar_asset in ownership.asset_to_team:
                    asset_ids.append(sonar_asset)
        return _dedupe(asset_ids)


def _normalize_views(raw: list | None) -> frozenset[str]:
    allowed = {"developer", "executive", "platform"}
    out = {str(v) for v in (raw or []) if str(v) in allowed}
    return frozenset(out)


def _build_indexes(
    components: list[ComponentEntry],
) -> tuple[
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
    tuple[ApplicationIndex, ...],
    dict[str, ComponentEntry],
    dict[str, str],
    dict[str, frozenset[str]],
    tuple[str, ...],
]:
    app_teams: dict[str, list[str]] = {}
    app_repos: dict[str, list[str]] = {}
    app_labels: dict[str, str] = {}
    app_pillars: dict[str, str | None] = {}
    app_services: dict[str, list[str]] = {}
    by_key: dict[str, ComponentEntry] = {}
    wiz_service_to_team: dict[str, str] = {}
    wiz_teams_by_pillar: dict[str, set[str]] = {}
    dev_teams: list[str] = []

    for comp in components:
        by_key[comp.key] = comp
        app = comp.application.lower()
        app_labels.setdefault(app, comp.application_label)
        app_pillars.setdefault(app, comp.dev_pillar)
        if comp.repo and comp.repo not in (app_repos.get(app) or []):
            app_repos.setdefault(app, []).append(comp.repo)
        if comp.label not in (app_services.get(app) or []):
            app_services.setdefault(app, []).append(comp.label)
        for team in comp.teams:
            if team not in (app_teams.get(app) or []):
                app_teams.setdefault(app, []).append(team)
            if "developer" in comp.views and team not in dev_teams:
                dev_teams.append(team)
        if comp.wiz_service:
            if comp.wiz_service in wiz_service_to_team:
                raise ValueError(
                    f"duplicate wiz_service {comp.wiz_service!r} on keys "
                    f"{wiz_service_to_team[comp.wiz_service]!r} and {comp.key!r}"
                )
            wiz_service_to_team[comp.wiz_service] = comp.teams[0]
            if comp.dev_pillar:
                wiz_teams_by_pillar.setdefault(comp.dev_pillar, set()).add(comp.teams[0])
                for extra in comp.teams[1:]:
                    wiz_teams_by_pillar[comp.dev_pillar].add(extra)

    applications = tuple(
        ApplicationIndex(
            key=app_key,
            label=app_labels[app_key],
            services=tuple(app_services.get(app_key, [])),
            repos=tuple(app_repos.get(app_key, [])),
            teams=_dedupe(app_teams.get(app_key, [])),
            dev_pillar=app_pillars.get(app_key),
        )
        for app_key in app_labels
    )

    return (
        {k: _dedupe(v) for k, v in app_teams.items()},
        {k: tuple(v) for k, v in app_repos.items()},
        applications,
        by_key,
        wiz_service_to_team,
        {k: frozenset(v) for k, v in wiz_teams_by_pillar.items()},
        _dedupe(dev_teams),
    )


def parse_component_registry(text: str) -> ComponentRegistry:
    raw = yaml.safe_load(text) or {}
    version = int(raw.get("version") or 1)

    pillars: list[ExecutivePillar] = []
    for key, cfg in (raw.get("executive_pillars") or {}).items():
        cfg = cfg or {}
        sub_raw = cfg.get("sub_teams") or []
        sub_teams = tuple(
            ExecutiveSubTeam(
                label=str(s.get("label") or ""),
                team_key=s.get("team_key"),
            )
            for s in sub_raw
            if isinstance(s, dict)
        )
        team_keys = [str(t) for t in (cfg.get("team_keys") or [])]
        if not team_keys and sub_teams:
            team_keys = [s.team_key for s in sub_teams if s.team_key]
        pillars.append(
            ExecutivePillar(
                key=str(key),
                label=str(cfg.get("label") or key),
                team_keys=_dedupe(team_keys),
                sub_teams=sub_teams,
            )
        )

    components: list[ComponentEntry] = []
    for item in raw.get("components") or []:
        if not isinstance(item, dict):
            continue
        teams = tuple(str(t) for t in (item.get("teams") or []))
        sonar = tuple(str(s) for s in (item.get("sonar_projects") or []))
        repo = item.get("repo")
        wiz = item.get("wiz_service")
        components.append(
            ComponentEntry(
                key=str(item.get("key") or ""),
                label=str(item.get("label") or item.get("key") or ""),
                application=str(item.get("application") or ""),
                application_label=str(
                    item.get("application_label") or item.get("application") or ""
                ),
                teams=teams,
                views=_normalize_views(item.get("views")),
                dev_pillar=item.get("dev_pillar"),
                repo=str(repo) if repo else None,
                sonar_projects=sonar,
                wiz_service=str(wiz) if wiz else None,
            )
        )

    (
        application_to_teams,
        application_to_repos,
        applications,
        component_by_key,
        wiz_service_to_team,
        wiz_teams_for_pillar,
        developer_scope_team_keys,
    ) = _build_indexes(components)

    return ComponentRegistry(
        version=version,
        components=tuple(components),
        executive_pillars=tuple(pillars),
        out_of_view_teams=frozenset(str(t) for t in (raw.get("out_of_view_teams") or [])),
        application_to_teams=application_to_teams,
        application_to_repos=application_to_repos,
        applications=applications,
        component_by_key=component_by_key,
        wiz_service_to_team=wiz_service_to_team,
        wiz_teams_for_pillar=wiz_teams_for_pillar,
        developer_scope_team_keys=developer_scope_team_keys,
        loaded_at=time.time(),
    )


def enrich_registry_wiz_indexes(
    registry: ComponentRegistry,
    supplemental: dict[str, str],
) -> ComponentRegistry:
    """Merge config/wiz_service_team_map.yaml into derived Wiz indexes."""
    if not supplemental:
        return registry
    wiz_service_to_team = dict(registry.wiz_service_to_team)
    wiz_teams_by_pillar = {k: set(v) for k, v in registry.wiz_teams_for_pillar.items()}
    team_to_pillars: dict[str, set[str]] = {}
    for pillar in registry.executive_pillars:
        for team in pillar.team_keys:
            team_to_pillars.setdefault(team, set()).add(pillar.key)
    for slug, team in supplemental.items():
        wiz_service_to_team.setdefault(slug, team)
        for pillar in team_to_pillars.get(team, ()):
            wiz_teams_by_pillar.setdefault(pillar, set()).add(team)
    return replace(
        registry,
        wiz_service_to_team=wiz_service_to_team,
        wiz_teams_for_pillar={k: frozenset(v) for k, v in wiz_teams_by_pillar.items()},
    )


def component_key_from_service(service: str) -> str:
    """Stable kebab-case id for `?service=` URLs (matches generator)."""
    return re.sub(r"[^a-z0-9]+", "-", service.lower()).strip("-") or "unknown"
