"""Platform pillar team sets for asymmetric per-source narrowing.

SonarCloud + Dependabot stay scoped to one platform team per tab; Wiz spans every
team in the pillar that carries a `wiz_service:` registry entry. Unowned Wiz rows
are scoped by `platform_pillar:*` tags from config/wiz_subscription_pillar.yaml.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Select, and_, false, or_

from app.core.models import DailyMetric, Finding
from app.core.wiz_subscription_pillar import (
    THREAT_INTEL_PILLAR,
    is_threat_intel_pillar,
    platform_code_team_for_pillar,
    platform_pillar_tag,
)
from app.normalizer.processor import UNOWNED_TEAM

_PLATFORM_CODE_SOURCES = frozenset({"sonarcloud", "dependabot", "pentest"})

def platform_code_teams(pillar: str) -> frozenset[str]:
    team = platform_code_team_for_pillar(pillar)
    return frozenset({team}) if team else frozenset()


def _wiz_threat_intel_clause():
    """Org-wide Wiz Threat Center advisories (30d) — not tied to a product line."""
    return and_(
        Finding.source == "wiz",
        Finding.owner_team == UNOWNED_TEAM,
        Finding.tags.any(platform_pillar_tag(THREAT_INTEL_PILLAR)),
        Finding.wiz_category == "threat_center",
    )


def _wiz_unowned_for_pillar(pillar: str):
    if is_threat_intel_pillar(pillar):
        return _wiz_threat_intel_clause()
    tag = platform_pillar_tag(pillar)
    return and_(
        Finding.source == "wiz",
        Finding.owner_team == UNOWNED_TEAM,
        Finding.tags.any(tag),
        or_(Finding.wiz_category.is_(None), Finding.wiz_category != "threat_center"),
    )


def _wiz_owned_for_teams(wiz_teams: frozenset[str] | list[str] | tuple[str, ...]):
    if not wiz_teams:
        return None
    return and_(
        Finding.source == "wiz",
        Finding.owner_team.in_(list(wiz_teams)),
    )


def _wiz_platform_code_owned_for_pillar(pillar: str):
    """Wiz on orphan cloud resources stamped to the tab's platform code team."""
    if is_threat_intel_pillar(pillar):
        return None
    code_teams = platform_code_teams(pillar)
    if not code_teams:
        return None
    return and_(
        Finding.source == "wiz",
        Finding.owner_team.in_(list(code_teams)),
        Finding.tags.any(platform_pillar_tag(pillar)),
        or_(Finding.wiz_category.is_(None), Finding.wiz_category != "threat_center"),
    )


def platform_pillar_asymmetric_clause(
    pillar: str,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...],
) -> ColumnElement[bool]:
    """OR of per-source scopes used by /platform rating cards."""
    if is_threat_intel_pillar(pillar):
        return _wiz_threat_intel_clause()
    code_teams = platform_code_teams(pillar)
    clauses: list[ColumnElement[bool]] = []
    if code_teams:
        code_team_list = list(code_teams)
        for src in _PLATFORM_CODE_SOURCES:
            clauses.append(
                and_(Finding.source == src, Finding.owner_team.in_(code_team_list))
            )
    wiz_parts: list[ColumnElement[bool]] = [_wiz_unowned_for_pillar(pillar)]
    owned = _wiz_owned_for_teams(wiz_teams)
    if owned is not None:
        wiz_parts.insert(0, owned)
    code_owned = _wiz_platform_code_owned_for_pillar(pillar)
    if code_owned is not None:
        wiz_parts.insert(0, code_owned)
    clauses.append(or_(*wiz_parts))
    return or_(*clauses) if clauses else false()


def platform_pillar_source_clause(
    pillar: str,
    source: str,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...],
) -> ColumnElement[bool]:
    """Per-source team scope for a single `?source=` filter on /platform."""
    if is_threat_intel_pillar(pillar):
        return _wiz_threat_intel_clause() if source == "wiz" else false()
    if source == "wiz":
        wiz_parts: list[ColumnElement[bool]] = [_wiz_unowned_for_pillar(pillar)]
        owned = _wiz_owned_for_teams(wiz_teams)
        if owned is not None:
            wiz_parts.insert(0, owned)
        code_owned = _wiz_platform_code_owned_for_pillar(pillar)
        if code_owned is not None:
            wiz_parts.insert(0, code_owned)
        return and_(Finding.source == "wiz", or_(*wiz_parts))
    if source in _PLATFORM_CODE_SOURCES:
        code_teams = platform_code_teams(pillar)
        if not code_teams:
            return false()
        return and_(Finding.source == source, Finding.owner_team.in_(list(code_teams)))
    return false()


def apply_platform_pillar_asymmetric_scope(
    query: Select,
    pillar: str,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...],
) -> Select:
    """Match /platform Overview totals to the per-source rating cards."""
    return query.where(platform_pillar_asymmetric_clause(pillar, wiz_teams))


def apply_platform_pillar_finding_scope(
    query: Select,
    pillar: str,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...],
    *,
    sources: list[str] | None = None,
) -> Select:
    """Apply /platform asymmetric narrowing, honouring an optional `?source=` filter."""
    if sources:
        clauses = [
            platform_pillar_source_clause(pillar, src, wiz_teams) for src in sources
        ]
        return query.where(or_(*clauses))
    return apply_platform_pillar_asymmetric_scope(query, pillar, wiz_teams)


def apply_finding_team_scope(
    query: Select,
    teams: frozenset[str] | list[str] | tuple[str, ...] | None,
    *,
    platform_pillar: str | None,
) -> Select:
    """Narrow Wiz by pillar tab scope (registry teams, unowned, platform code team)."""
    if platform_pillar:
        wiz_parts: list[ColumnElement[bool]] = [_wiz_unowned_for_pillar(platform_pillar)]
        owned = _wiz_owned_for_teams(teams or frozenset())
        if owned is not None:
            wiz_parts.insert(0, owned)
        code_owned = _wiz_platform_code_owned_for_pillar(platform_pillar)
        if code_owned is not None:
            wiz_parts.insert(0, code_owned)
        return query.where(or_(*wiz_parts))
    if teams:
        return query.where(Finding.owner_team.in_(list(teams)))
    return query


def platform_pillar_daily_metric_clause(
    pillar: str,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...],
) -> ColumnElement[bool]:
    """Asymmetric `(team, source)` filter for `daily_metrics` (no tag dimension).

    Unowned Wiz is omitted here — rollup rows are keyed only by `team='unowned'`.
    `/metrics/trend?platform_pillar=` uses event replay instead so unowned Wiz
    matches `/metrics/security-posture`.
    """
    code_teams = platform_code_teams(pillar)
    clauses: list[ColumnElement[bool]] = []
    if code_teams:
        code_team_list = list(code_teams)
        for src in _PLATFORM_CODE_SOURCES:
            clauses.append(
                and_(DailyMetric.source == src, DailyMetric.team.in_(code_team_list))
            )
    if wiz_teams:
        clauses.append(
            and_(
                DailyMetric.source == "wiz",
                DailyMetric.team.in_(list(wiz_teams)),
            )
        )
    if code_teams:
        clauses.append(
            and_(
                DailyMetric.source == "wiz",
                DailyMetric.team.in_(list(code_teams)),
            )
        )
    return or_(*clauses) if clauses else false()


def apply_daily_metric_team_scope(
    query: Select,
    teams: frozenset[str] | list[str] | tuple[str, ...] | None,
    *,
    platform_pillar: str | None,
    wiz_teams: frozenset[str] | list[str] | tuple[str, ...] | None = None,
) -> Select:
    """Trend rollup scope — plain team union, or asymmetric per-source when on /platform."""
    if platform_pillar:
        return query.where(
            platform_pillar_daily_metric_clause(
                platform_pillar, wiz_teams or frozenset()
            )
        )
    if teams:
        return query.where(DailyMetric.team.in_(list(teams)))
    return query
