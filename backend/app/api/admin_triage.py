"""Admin triage scope for `/admin` unowned sections.

Findings with `owner_team='unowned'` that already surface on `/developer` or
`/platform` are excluded from `?team=unowned` queries so operators triage only
genuinely orphaned rows.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Select, not_, or_

from app.api.platform_pillar import _wiz_threat_intel_clause, _wiz_unowned_for_pillar
from app.core.component_registry import ComponentRegistry
from app.core.config_store import OwnershipMap
from app.core.models import Finding
from app.core.wiz_subscription_pillar import platform_code_team_for_pillar
from app.normalizer.processor import UNOWNED_TEAM


def is_admin_triage_unowned_teams(team: list[str] | None) -> bool:
    return team is not None and set(team) == {UNOWNED_TEAM}


def _consumer_visible_teams(registry: ComponentRegistry) -> frozenset[str]:
    teams: set[str] = set(registry.developer_scope_team_keys)
    for pillar in registry.executive_pillars:
        code_team = platform_code_team_for_pillar(pillar.key)
        if code_team:
            teams.add(code_team)
        teams.update(registry.wiz_teams_for_pillar.get(pillar.key, ()))
    teams.discard(UNOWNED_TEAM)
    teams.discard("excluded")
    return frozenset(teams)


def _consumer_visible_asset_ids(
    registry: ComponentRegistry,
    ownership: OwnershipMap,
) -> tuple[str, ...]:
    visible_teams = _consumer_visible_teams(registry)
    asset_ids: set[str] = set()
    for asset_id, team in ownership.asset_to_team.items():
        if team in visible_teams:
            asset_ids.add(asset_id)
    for slug, team in registry.wiz_service_to_team.items():
        if team in visible_teams:
            asset_ids.add(f"wizservice:{slug}")
    return tuple(asset_ids)


def _platform_unowned_wiz_visible_clause(
    registry: ComponentRegistry,
) -> ColumnElement[bool]:
    clauses = [_wiz_unowned_for_pillar(pillar.key) for pillar in registry.executive_pillars]
    clauses.append(_wiz_threat_intel_clause())
    return or_(*clauses)


def admin_triage_unowned_exclusion_clause(
    registry: ComponentRegistry,
    ownership: OwnershipMap,
) -> ColumnElement[bool]:
    """True when an unowned row is already visible on /developer or /platform."""
    parts: list[ColumnElement[bool]] = [_platform_unowned_wiz_visible_clause(registry)]
    asset_ids = _consumer_visible_asset_ids(registry, ownership)
    if asset_ids:
        parts.append(Finding.asset_id.in_(list(asset_ids)))
    return or_(*parts)


def apply_admin_triage_unowned_scope(
    query: Select,
    registry: ComponentRegistry,
    ownership: OwnershipMap,
) -> Select:
    return query.where(
        not_(admin_triage_unowned_exclusion_clause(registry, ownership))
    )
