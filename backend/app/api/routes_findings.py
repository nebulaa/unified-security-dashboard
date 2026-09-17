"""`GET /findings` and `GET /findings/{id}` — RBAC-scoped finding browser.

Query parameters mirror what the table UI exposes for filter + sort:

  Filters (all combinable, all server-side, all reflected in the `total` count):
    severity                           repeatable; OR within (e.g. ?severity=critical&severity=high)
    status                             repeatable; OR within
    team, source                       enum equality
    title                              case-insensitive substring on title
    asset                              case-insensitive substring on asset_display
    sla_breached                       boolean; computed from severity + sla.yaml

  Sort:
    sort_by  ∈ {severity, status, title, asset, team, source, age, sla}
    sort_dir ∈ {asc, desc}             default per column

The SLA-breach filter is translated to SQL using the per-severity windows from
`sla.yaml` so pagination + totals stay correct (the previous Python-side filter
was wrong for `total` and for `limit + offset` math).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.admin_triage import (
    apply_admin_triage_unowned_scope,
    is_admin_triage_unowned_teams,
)
from app.api.deps import current_user, db_session
from app.api.platform_pillar import (
    apply_finding_team_scope,
    apply_platform_pillar_finding_scope,
)
from app.api.schemas import (
    FindingDetail,
    FindingEventResponse,
    FindingListResponse,
    FindingSummary,
    WizCategoryGroup,
    WizFindingsByCategoryResponse,
    WizTitleGroup,
)
from app.api.scoping import ADMIN_ONLY_SOURCES, apply_finding_scope
from app.api.sla import age_seconds, is_breached
from app.core.config_store import get_config_cache
from app.core.enums import Severity, Status
from app.core.models import Finding
from app.core.policy import SlaPolicy, get_policy_cache
from app.core.rbac import UserContext
from app.core.scope_resolver import resolve_scope
from app.core.wiz_portal import WIZ_CATEGORY_LABELS, WIZ_CATEGORY_ORDER, wiz_portal_url
from app.core.wiz_subscription_pillar import is_threat_intel_pillar
from app.normalizer.mappers.wiz import WIZ_CATEGORIES

router = APIRouter(prefix="/findings", tags=["findings"])

SortKey = Literal["severity", "status", "title", "asset", "team", "source", "age", "sla"]
SortDir = Literal["asc", "desc"]

# Default sort direction per key. Severity/status enums sort naturally (critical
# first), age + sla intuitively want oldest/most-breached first.
_DEFAULT_DIR: dict[str, str] = {
    "severity": "asc",
    "status": "asc",
    "title": "asc",
    "asset": "asc",
    "team": "asc",
    "source": "asc",
    "age": "desc",
    "sla": "desc",
}

# SQL expression for the SLA / age anchor, mirrors `Finding.sla_started_at`.
# `reopened_at` is intentionally not in the coalesce chain — see `app/api/sla.py`
# for why (auto_close + reopen lifecycle reset the age clock for valid old
# findings whenever absent-detection misfired, e.g. the SonarCloud multi-org
# cross-contamination in commit 8d11948).
_SLA_ANCHOR = func.coalesce(Finding.upstream_created_at, Finding.first_seen_at)


def _to_summary(f: Finding, now: datetime, sla: SlaPolicy) -> FindingSummary:
    anchor = f.sla_started_at  # upstream_created_at > first_seen_at
    upstream_url = None
    if f.source == "wiz":
        upstream_url = f.upstream_url or wiz_portal_url(f.native_id, f.wiz_category)
    return FindingSummary(
        id=f.id,
        source=f.source,
        native_id=f.native_id,
        title=f.title,
        severity=f.severity,
        status=f.status,
        cve_id=f.cve_id,
        asset_display=f.asset_display,
        owner_team=f.owner_team,
        first_seen_at=f.first_seen_at,
        last_seen_at=f.last_seen_at,
        upstream_created_at=f.upstream_created_at,
        reopened_at=f.reopened_at,
        sla_started_at=anchor,
        age_days=age_seconds(anchor, now) / 86_400,
        sla_breached=is_breached(sla, f.severity, f.status, anchor, now),
        wiz_category=f.wiz_category,
        upstream_url=upstream_url,
    )


_WIZ_TITLE_GROUP_CATEGORIES = frozenset({"issue", "cloud_config", "vulnerability"})

_TITLE_GROUP_FALLBACK: dict[str, str] = {
    "issue": "Unknown issue",
    "cloud_config": "Unknown misconfiguration",
    "vulnerability": "Unknown CVE",
}


def _wiz_title_group_key(row: Finding) -> str:
    if row.wiz_category == "vulnerability":
        cve = (row.cve_id or "").strip()
        if cve:
            return cve
    title = (row.title or "").strip()
    if title:
        return title
    cat = row.wiz_category or "unknown"
    return _TITLE_GROUP_FALLBACK.get(cat, "Unknown finding")


def _build_wiz_title_groups(
    rows: list[Finding],
    *,
    limit_per_group: int,
    now: datetime,
    sla: SlaPolicy,
) -> list[WizTitleGroup]:
    """Group rows by title (issues/controls) or CVE id (vulnerabilities)."""
    grouped: dict[str, list[Finding]] = {}
    for row in rows:
        grouped.setdefault(_wiz_title_group_key(row), []).append(row)

    groups: list[WizTitleGroup] = []
    for title in sorted(grouped, key=lambda t: (-len(grouped[t]), t.lower())):
        items = grouped[title]
        sample = items[:limit_per_group]
        groups.append(
            WizTitleGroup(
                title=title,
                count=len(items),
                items=[_to_summary(f, now, sla) for f in sample],
            )
        )
    return groups


def _category_group(
    cat: str,
    *,
    counts: dict[str, int],
    by_category: dict[str, list[Finding]],
    title_group_rows: dict[str, list[Finding]],
    limit_per_category: int,
    now: datetime,
    sla: SlaPolicy,
) -> WizCategoryGroup:
    items = by_category.get(cat, [])
    title_groups = None
    grouped_rows = title_group_rows.get(cat)
    if cat in _WIZ_TITLE_GROUP_CATEGORIES and grouped_rows:
        title_groups = _build_wiz_title_groups(
            grouped_rows,
            limit_per_group=limit_per_category,
            now=now,
            sla=sla,
        )
    label = WIZ_CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
    return WizCategoryGroup(
        wiz_category=cat,
        label=label,
        count=counts.get(cat, 0),
        items=[_to_summary(f, now, sla) for f in items],
        title_groups=title_groups,
    )


def _sla_breach_predicate(sla: SlaPolicy, now: datetime, breached: bool):
    """Build a SQL predicate that matches `is_breached(...)` from app/api/sla.py.

    Closed findings are never breached. For each severity with a finite window,
    a finding is breached when `_SLA_ANCHOR < now - window`. We OR these per-severity
    clauses; severities without an SLA window (e.g. `info`) are always-not-breached.
    """
    open_clauses = [Finding.status == s for s in Status.open_set()]
    is_open = or_(*open_clauses)

    breach_clauses = []
    for sev in Severity:
        window = sla.window_seconds(sev.value)
        if window is None:
            continue
        cutoff = now - timedelta(seconds=window)
        breach_clauses.append(and_(Finding.severity == sev, cutoff > _SLA_ANCHOR))

    if not breach_clauses:
        # No SLA windows defined → nothing is ever breached.
        return Finding.id.is_(None) if breached else Finding.id.isnot(None)

    breach_expr = and_(is_open, or_(*breach_clauses))
    return breach_expr if breached else ~breach_expr


def _apply_sort(stmt: Select, sort_by: str, sort_dir: str) -> Select:
    """Map a sort_by key to a SQLAlchemy ORDER BY. Falls back to severity asc + age desc."""
    desc = sort_dir == "desc"

    column_map = {
        "severity": Finding.severity,
        "status": Finding.status,
        "title": func.lower(Finding.title),  # case-insensitive
        "asset": func.lower(Finding.asset_display),
        "team": Finding.owner_team,
        "source": Finding.source,
        "age": _SLA_ANCHOR,  # NB: oldest = smallest anchor; "desc age" = oldest first
    }

    if sort_by == "sla":
        # SLA sort = "most breached first" = oldest anchor first when desc.
        # We can't compute the actual breach boolean efficiently in ORDER BY, so we
        # approximate by anchor + severity (criticals dominate breach impact).
        anchor_dir = _SLA_ANCHOR.asc() if desc else _SLA_ANCHOR.desc()
        return stmt.order_by(Finding.severity.asc(), anchor_dir, Finding.id.asc())

    primary = column_map[sort_by]
    if sort_by == "age":
        # Oldest first when desc -> ascending anchor; newest first when asc -> descending anchor.
        primary = primary.asc() if desc else primary.desc()
    else:
        primary = primary.desc() if desc else primary.asc()

    return stmt.order_by(primary, Finding.id.asc())


@router.get("", response_model=FindingListResponse)
def list_findings(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    source_in: Annotated[
        list[str] | None,
        Query(
            alias="source",
            description="Filter by source. Repeat for union semantics (e.g. Platform Product tab).",
        ),
    ] = None,
    severity_in: Annotated[list[Severity] | None, Query(alias="severity")] = None,
    status_in: Annotated[list[Status] | None, Query(alias="status")] = None,
    team: Annotated[
        list[str] | None,
        Query(description="Filter by owner team. Repeat the param for union semantics."),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    title: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    asset: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    wiz_category: Annotated[str | None, Query()] = None,
    platform_pillar: Annotated[
        str | None,
        Query(
            description=(
                "Platform view tab (product / retail / io). When set, unowned "
                "Wiz findings are included alongside scoped teams."
            ),
        ),
    ] = None,
    sla_breached: Annotated[bool | None, Query()] = None,
    sort_by: Annotated[SortKey, Query()] = "severity",
    sort_dir: Annotated[SortDir | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FindingListResponse:
    # Admin-only sources (today: `sonarcloud_trivy`) are hidden by default in
    # `apply_finding_scope`. The /admin page surfaces them via the dedicated
    # "Trivy issues in SonarCloud" section by explicitly asking for them on
    # the wire. We honour that opt-in only for users who actually hold the
    # admin role; everyone else gets a 403 (rather than a silent empty result)
    # so a misconfigured client fails loudly.
    if wiz_category:
        if wiz_category not in WIZ_CATEGORIES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"unknown wiz_category {wiz_category!r}; "
                f"expected one of {sorted(WIZ_CATEGORIES)}",
            )
        if source_in and "wiz" not in source_in:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "wiz_category filter requires source=wiz",
            )

    if source_in and any(s in ADMIN_ONLY_SOURCES for s in source_in) and not user.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "one or more requested sources are admin-only",
        )
    include_admin_only = bool(
        source_in and any(s in ADMIN_ONLY_SOURCES for s in source_in)
    )
    effective_service = service or server
    cache = get_config_cache()
    try:
        scope = resolve_scope(
            ownership=cache.get_ownership(),
            scope_map=cache.get_scope_map(),
            registry=cache.get_component_registry(),
            team=team,
            executive_pillar=executive_pillar,
            pillar_alias=pillar,
            jira_project=jira_project,
            application=application,
            service=effective_service,
            repo=repo,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    base = apply_finding_scope(
        select(Finding),
        user,
        include_admin_only_sources=include_admin_only,
    )

    if source_in:
        base = base.where(Finding.source.in_(source_in))
    if wiz_category:
        base = base.where(Finding.wiz_category == wiz_category)
    if severity_in:
        base = base.where(Finding.severity.in_(severity_in))
    if status_in:
        base = base.where(Finding.status.in_(status_in))
    else:
        base = base.where(Finding.status.in_(list(Status.open_set())))
    if platform_pillar:
        wiz_teams = cache.get_component_registry().wiz_teams_for_pillar.get(
            platform_pillar, frozenset()
        )
        base = apply_platform_pillar_finding_scope(
            base,
            platform_pillar,
            wiz_teams,
            sources=source_in,
        )
    else:
        base = apply_finding_team_scope(
            base, scope.teams, platform_pillar=platform_pillar
        )
    if is_admin_triage_unowned_teams(team):
        base = apply_admin_triage_unowned_scope(
            base,
            cache.get_component_registry(),
            cache.get_ownership(),
        )
    if scope.repo_asset_ids:
        base = base.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if title:
        base = base.where(Finding.title.ilike(f"%{title}%"))
    asset_terms = list(scope.asset_terms)
    if asset:
        asset_terms.append(asset)
    if asset_terms:
        base = base.where(
            or_(*[Finding.asset_display.ilike(f"%{term}%") for term in asset_terms])
        )

    sla = get_policy_cache().get_sla()
    now = datetime.now(UTC)

    if sla_breached is not None:
        base = base.where(_sla_breach_predicate(sla, now, sla_breached))

    effective_dir = sort_dir or _DEFAULT_DIR[sort_by]
    ordered = _apply_sort(base, sort_by, effective_dir)

    rows = list(session.scalars(ordered.limit(limit).offset(offset)))
    summaries = [_to_summary(f, now, sla) for f in rows]

    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0

    return FindingListResponse(items=summaries, total=int(total), limit=limit, offset=offset)


@router.get("/wiz-by-category", response_model=WizFindingsByCategoryResponse)
def list_wiz_findings_by_category(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    team: Annotated[
        list[str] | None,
        Query(description="Filter by owner team. Repeat the param for union semantics."),
    ] = None,
    platform_pillar: Annotated[
        str | None,
        Query(
            description=(
                "Platform view tab (product / retail / io). When set, unowned "
                "Wiz findings are included alongside scoped teams."
            ),
        ),
    ] = None,
    severity_in: Annotated[list[Severity] | None, Query(alias="severity")] = None,
    status_in: Annotated[list[Status] | None, Query(alias="status")] = None,
    sla_breached: Annotated[bool | None, Query()] = None,
    limit_per_category: Annotated[int, Query(ge=1, le=100)] = 50,
) -> WizFindingsByCategoryResponse:
    """Open Wiz findings grouped by wiz_category for /platform/wiz and /developer/wiz."""
    cache = get_config_cache()
    try:
        scope = resolve_scope(
            ownership=cache.get_ownership(),
            scope_map=cache.get_scope_map(),
            registry=cache.get_component_registry(),
            team=team,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    base = apply_finding_scope(select(Finding), user)
    base = base.where(Finding.source == "wiz")
    if severity_in:
        base = base.where(Finding.severity.in_(severity_in))
    else:
        base = base.where(Finding.severity.in_([Severity.critical, Severity.high]))
    if status_in:
        base = base.where(Finding.status.in_(status_in))
    else:
        base = base.where(Finding.status.in_(list(Status.open_set())))
    if platform_pillar:
        wiz_teams = cache.get_component_registry().wiz_teams_for_pillar.get(
            platform_pillar, frozenset()
        )
        base = apply_platform_pillar_finding_scope(
            base,
            platform_pillar,
            wiz_teams,
            sources=["wiz"],
        )
    else:
        base = apply_finding_team_scope(
            base, scope.teams, platform_pillar=platform_pillar
        )
    if scope.repo_asset_ids:
        base = base.where(Finding.asset_id.in_(scope.repo_asset_ids))

    sla = get_policy_cache().get_sla()
    now = datetime.now(UTC)
    if sla_breached is not None:
        base = base.where(_sla_breach_predicate(sla, now, sla_breached))

    if platform_pillar and is_threat_intel_pillar(platform_pillar):
        base = base.where(Finding.wiz_category == "threat_center")
    elif platform_pillar:
        base = base.where(
            or_(Finding.wiz_category.is_(None), Finding.wiz_category != "threat_center")
        )

    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0

    ordered = _apply_sort(base, "severity", "asc")
    rows = list(session.scalars(ordered))
    by_category: dict[str, list[Finding]] = {}
    title_group_rows: dict[str, list[Finding]] = {}
    for row in rows:
        cat = row.wiz_category or "unknown"
        if cat in _WIZ_TITLE_GROUP_CATEGORIES:
            title_group_rows.setdefault(cat, []).append(row)
        bucket = by_category.setdefault(cat, [])
        if len(bucket) < limit_per_category:
            bucket.append(row)

    categories: list[WizCategoryGroup] = []
    counts: dict[str, int] = {}
    for row in rows:
        cat = row.wiz_category or "unknown"
        counts[cat] = counts.get(cat, 0) + 1

    for cat in WIZ_CATEGORY_ORDER:
        if platform_pillar and is_threat_intel_pillar(platform_pillar) and cat != "threat_center":
            continue
        if platform_pillar and not is_threat_intel_pillar(platform_pillar) and cat == "threat_center":
            continue
        if counts.get(cat, 0) == 0:
            continue
        categories.append(
            _category_group(
                cat,
                counts=counts,
                by_category=by_category,
                title_group_rows=title_group_rows,
                limit_per_category=limit_per_category,
                now=now,
                sla=sla,
            )
        )
    for cat in sorted(counts):
        if cat in WIZ_CATEGORY_ORDER:
            continue
        categories.append(
            _category_group(
                cat,
                counts=counts,
                by_category=by_category,
                title_group_rows=title_group_rows,
                limit_per_category=limit_per_category,
                now=now,
                sla=sla,
            )
        )

    return WizFindingsByCategoryResponse(total=int(total), categories=categories)


@router.get("/{finding_id}", response_model=FindingDetail)
def get_finding(
    finding_id: UUID,
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
) -> FindingDetail:
    # Admins (and only admins) can deep-link into an admin-only-source finding
    # detail; for everyone else the default exclusion makes that ID invisible
    # and the call returns a 404 (consistent with "not in scope").
    base = apply_finding_scope(
        select(Finding).options(selectinload(Finding.events)).where(Finding.id == finding_id),
        user,
        include_admin_only_sources=user.is_admin,
    )
    f = session.scalars(base).one_or_none()
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found or not in scope")

    sla = get_policy_cache().get_sla()
    now = datetime.now(UTC)
    summary = _to_summary(f, now, sla)

    return FindingDetail(
        **summary.model_dump(),
        description=f.description,
        cwe_id=f.cwe_id,
        asset_id=f.asset_id,
        asset_type=f.asset_type,
        asset_root=f.asset_root,
        correlation_group_id=f.correlation_group_id,
        consecutive_misses=f.consecutive_misses,
        raw_payload_uri=f.raw_payload_uri,
        tags=list(f.tags),
        events=[
            FindingEventResponse(
                event_type=e.event_type,
                from_value=e.from_value,
                to_value=e.to_value,
                occurred_at=e.occurred_at,
                actor=e.actor,
                reason=e.reason,
            )
            for e in f.events
        ],
    )
