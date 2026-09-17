from __future__ import annotations

from dataclasses import dataclass

from app.core.component_registry import ComponentRegistry
from app.core.config_store import OwnershipMap, ScopeMap


@dataclass(frozen=True)
class ResolvedScope:
    teams: tuple[str, ...] = ()
    repo_asset_ids: tuple[str, ...] = ()
    asset_terms: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


def _repo_asset_id(repo: str) -> str:
    return f"repo:{repo}"


def _resolve_repo_filter(repo: str, ownership: OwnershipMap) -> tuple[str, ...]:
    raw = repo.strip()
    if not raw:
        return ()
    if "/" in raw:
        return (_repo_asset_id(raw),)

    suffix = f"/{raw}"
    matches = sorted(
        asset_id
        for asset_id in ownership.asset_to_team
        if asset_id.startswith("repo:") and asset_id.endswith(suffix)
    )
    if len(matches) == 1:
        return (matches[0],)
    if len(matches) > 1:
        raise ValueError(
            f"repo '{raw}' is ambiguous; use org/repo (matches: {', '.join(matches)})"
        )
    return (_repo_asset_id(raw),)


def resolve_scope(
    *,
    ownership: OwnershipMap,
    scope_map: ScopeMap,
    registry: ComponentRegistry | None = None,
    team: list[str] | None = None,
    executive_pillar: str | None = None,
    pillar_alias: str | None = None,
    jira_project: str | None = None,
    application: str | None = None,
    service: str | None = None,
    repo: str | None = None,
) -> ResolvedScope:
    teams: list[str] = list(team or [])
    warnings: list[str] = []

    pillar_key = executive_pillar or pillar_alias
    if pillar_alias and not executive_pillar:
        warnings.append("`pillar` is deprecated; use `executive_pillar`")
    if pillar_key:
        if registry is not None:
            teams.extend(registry.teams_for_executive_pillar(pillar_key))
        else:
            teams.extend(scope_map.teams_for_executive_pillar(pillar_key))

    if jira_project:
        project = jira_project.strip().upper()
        teams.extend(
            cfg.name
            for cfg in ownership.teams.values()
            if (cfg.jira_project or "").upper() == project
        )

    repo_asset_ids: list[str] = []
    if application:
        if registry is not None:
            teams.extend(registry.teams_for_application(application))
            repo_asset_ids.extend(
                registry.repo_asset_ids_for_application(application, ownership)
            )
        else:
            teams.extend(scope_map.teams_for_application(application))

    if service:
        if registry is not None:
            comp = registry.component_by_key.get(service.lower())
            if comp is None:
                norm = service.lower().replace("-", "").replace("_", "")
                for key, entry in registry.component_by_key.items():
                    if key.replace("-", "") == norm:
                        comp = entry
                        break
            if comp:
                teams.extend(comp.teams)
                if comp.repo:
                    repo_asset_ids.extend(_resolve_repo_filter(comp.repo, ownership))
                for sp in comp.sonar_projects:
                    repo_asset_ids.append(f"sonarproj:{sp}")
            else:
                teams.extend(scope_map.teams_for_service(service))
        else:
            teams.extend(scope_map.teams_for_service(service))

    if repo:
        repo_asset_ids.extend(_resolve_repo_filter(repo, ownership))

    return ResolvedScope(
        teams=_dedupe(teams),
        repo_asset_ids=_dedupe(repo_asset_ids),
        asset_terms=(),
        warnings=_dedupe(warnings),
    )
