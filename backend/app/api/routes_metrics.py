"""Metrics endpoints — KPI summary, trend, top teams, SLA breaches.

Every endpoint funnels through `apply_finding_scope`, which today does one
thing: keep admin-only sources (`sonarcloud_trivy`) out of the totals unless
the caller explicitly opted in. Pages narrow themselves by appending
`?team=` / `?source=`; there is no role-shaped scoping any more.

All time math uses `Finding.sla_started_at` (= upstream_created_at >
first_seen_at) so a 6-month-old GitHub alert ingested today is counted as 6
months old, not 1 day old. `reopened_at` is intentionally NOT in this
precedence — see `app/api/sla.py` for the rationale (it used to be, but
dashboard-internal auto_close + reopen cycles reset the age clock to "moments
ago" for valid old findings whenever absent-detection misfired).

Implementation notes:
  - `/trend` reads pre-aggregated `daily_metrics` (nightly rollup). When
    `?asset=` is set, falls back to per-day event replay (no asset dimension on rollup).
  - `/summary.mttr_critical_30d_seconds` uses `closed_at - sla_started_at` where
    `closed_at` is the most recent fixed/auto_closed/risk_accepted event in the last
    30 days. `auto_closed` counts as a closure for MTTR.
  - `/summary.open_criticals_wow_delta` compares now vs 7 days ago. It is
    nulled when the in-scope observation window (`MIN(first_seen_at)`) is
    younger than 7 days, because `_open_critical_count_at` uses the SLA anchor
    (`upstream_created_at`) to decide if a finding "existed 7d ago" — for Sonar
    findings whose upstream timestamps go back years, that retroactively
    projects every current critical as having been open last week and yields a
    confidently-wrong +0 WoW on a freshly seeded DB.
  - `/summary.observed_since` is the earliest `first_seen_at` in scope. The
    frontend uses it to render "history < 7d" / "history < 30d" hints on the
    WoW + MTTR KPI cards instead of misleading absolute deltas.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.admin_triage import (
    apply_admin_triage_unowned_scope,
    is_admin_triage_unowned_teams,
)
from app.api.deps import current_user, db_session
from app.api.platform_pillar import (
    apply_daily_metric_team_scope,
    apply_finding_team_scope,
    apply_platform_pillar_asymmetric_scope,
    platform_code_teams,
)
from app.api.schemas import (
    AgeBucketCounts,
    MetricsSummaryResponse,
    MetricsTrendResponse,
    RatingScoreBreakdown,
    SecurityPostureResponse,
    SeverityBreakdown,
    SlaBreachItem,
    SourceRating,
    SourceSeverityCount,
    TopAssetPoint,
    TopTeamPoint,
    TrendPoint,
)
from app.api.scoping import ADMIN_ONLY_SOURCES, apply_finding_scope
from app.api.sla import age_seconds, is_breached
from app.core.config_store import get_config_cache
from app.core.enums import EventType, Severity, Status
from app.core.models import DailyMetric, Finding, FindingEvent, ProcessedPayload
from app.core.policy import get_policy_cache
from app.core.rbac import UserContext
from app.core.scope_resolver import ResolvedScope, resolve_scope
from app.core.wiz_subscription_pillar import is_threat_intel_pillar
from app.normalizer.processor import UNOWNED_TEAM

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Platform teams on /executive whose Wiz exposure is infra/issues — not app repos.
# When `platform_wiz_issues_only=true`, leaderboards count Wiz Issues only for
# these teams (cloud_config / vulnerability rows are excluded).
_PLATFORM_WIZ_ISSUES_ONLY_TEAMS = frozenset(
    {"product-platform", "platform-retail", "io-platform-eng"}
)


def _apply_platform_wiz_issues_only(base):
    """Exclude non-issue Wiz rows owned by platform teams."""
    return base.where(
        or_(
            Finding.source != "wiz",
            Finding.owner_team.notin_(_PLATFORM_WIZ_ISSUES_ONLY_TEAMS),
            Finding.wiz_category == "issue",
        )
    )


def _apply_wiz_issues_only_filter(
    query,
    *,
    enabled: bool,
    platform_pillar: str | None = None,
):
    """Apply exec or platform-tab Wiz Issues narrowing when requested."""
    if not enabled:
        return query
    if platform_pillar and not is_threat_intel_pillar(platform_pillar):
        # Product-line platform tabs: Issues-only applies to Wiz rows only.
        # Non-Wiz sources keep wiz_category=NULL and must not be dropped.
        return query.where(
            or_(
                Finding.source != "wiz",
                Finding.wiz_category == "issue",
            )
        )
    return _apply_platform_wiz_issues_only(query)


def _open_status_values() -> list[str]:
    return [s.value for s in Status.open_set()]


# SQL expression for the SLA / age anchor; mirrors `Finding.sla_started_at`.
# `reopened_at` is deliberately excluded — see `app/api/sla.py`.
_SLA_ANCHOR = func.coalesce(Finding.upstream_created_at, Finding.first_seen_at)


def _resolve_request_scope(
    *,
    team: list[str] | None,
    executive_pillar: str | None,
    pillar: str | None,
    jira_project: str | None,
    application: str | None,
    service: str | None,
    server: str | None,
    repo: str | None,
) -> ResolvedScope:
    effective_service = service or server
    cache = get_config_cache()
    try:
        return resolve_scope(
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


def _open_critical_count_at(
    session: Session,
    user: UserContext,
    asof: datetime,
    scope: ResolvedScope | None = None,
    sources: list[str] | None = None,
    *,
    platform_wiz_issues_only: bool = False,
) -> int:
    base = apply_finding_scope(select(Finding.id, _SLA_ANCHOR.label("anchor")), user)
    base = base.where(Finding.severity == Severity.critical, asof >= _SLA_ANCHOR)
    if sources:
        base = base.where(Finding.source.in_(sources))
    if scope:
        if scope.teams:
            base = base.where(Finding.owner_team.in_(scope.teams))
        if scope.repo_asset_ids:
            base = base.where(Finding.asset_id.in_(scope.repo_asset_ids))
        if scope.asset_terms:
            asset_expr = [
                Finding.asset_display.ilike(f"%{term}%") for term in scope.asset_terms
            ]
            base = base.where(asset_expr[0] if len(asset_expr) == 1 else or_(*asset_expr))
    base = _apply_wiz_issues_only_filter(
        base, enabled=platform_wiz_issues_only
    )
    finding_rows = list(session.execute(base))

    if not finding_rows:
        return 0

    finding_ids = [row[0] for row in finding_rows]
    closing_event_types = (
        EventType.fixed,
        EventType.auto_closed,
        EventType.suppressed,
    )

    last_close = dict(
        session.execute(
            select(FindingEvent.finding_id, func.max(FindingEvent.occurred_at))
            .where(
                FindingEvent.finding_id.in_(finding_ids),
                FindingEvent.event_type.in_(closing_event_types),
                FindingEvent.occurred_at <= asof,
            )
            .group_by(FindingEvent.finding_id)
        ).all()
    )

    last_reopen = dict(
        session.execute(
            select(FindingEvent.finding_id, func.max(FindingEvent.occurred_at))
            .where(
                FindingEvent.finding_id.in_(finding_ids),
                FindingEvent.event_type == EventType.reopened,
                FindingEvent.occurred_at <= asof,
            )
            .group_by(FindingEvent.finding_id)
        ).all()
    )

    open_count = 0
    for fid, _anchor in finding_rows:
        closed_at = last_close.get(fid)
        reopened_at = last_reopen.get(fid)
        if closed_at is None or reopened_at and reopened_at > closed_at:
            open_count += 1
    return open_count


# ---------------------------------------------------------------------------
# Executive-view momentum + ageing helpers.
#
# All three share a single scope (RBAC + optional `?team=` multi-filter) with
# the rest of `metrics_summary`, so they live next to the existing helpers
# rather than in a sibling module.
# ---------------------------------------------------------------------------


# Inflow = a critical entering the open set: either freshly `discovered` or a
# previously auto_closed finding bouncing back via `reopened`. Both count
# toward "new risk this week" at exec level — a re-introduced vulnerability
# is exec-equivalent to a brand-new one.
_INFLOW_EVENTS = (EventType.discovered, EventType.reopened)

# Outflow = a critical leaving the open set under operator (or auto-close)
# action. `suppressed` is intentionally excluded — it's an out-of-policy
# escape hatch we don't currently emit, and counting it as "closed" would let
# noisy suppression masquerade as remediation in the burn-down number.
_OUTFLOW_EVENTS = (EventType.fixed, EventType.auto_closed)


def _critical_event_count(
    session: Session,
    user: UserContext,
    *,
    since: datetime,
    event_types: tuple[EventType, ...],
    scope: ResolvedScope | None,
    sources: list[str] | None = None,
    platform_wiz_issues_only: bool = False,
) -> int:
    """COUNT events of the given types on CRITICAL findings within scope.

    Filters in this order: RBAC scope (`apply_finding_scope`) → optional team
    union → severity=critical → event_type ∈ types → occurred_at ≥ since. The
    Finding join is needed for both the RBAC predicate and the severity filter
    (events don't carry severity directly).
    """
    q = (
        apply_finding_scope(
            select(func.count(FindingEvent.id))
            .select_from(FindingEvent)
            .join(Finding, Finding.id == FindingEvent.finding_id),
            user,
        )
        .where(
            Finding.severity == Severity.critical,
            FindingEvent.event_type.in_(event_types),
            FindingEvent.occurred_at >= since,
        )
    )
    if scope:
        if scope.teams:
            q = q.where(Finding.owner_team.in_(scope.teams))
        if scope.repo_asset_ids:
            q = q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if sources:
        q = q.where(Finding.source.in_(sources))
    q = _apply_wiz_issues_only_filter(q, enabled=platform_wiz_issues_only)
    return int(session.execute(q).scalar_one() or 0)


def _age_buckets_open_crit_high(
    session: Session,
    user: UserContext,
    now: datetime,
    scope: ResolvedScope | None,
    sources: list[str] | None = None,
    *,
    platform_wiz_issues_only: bool = False,
) -> AgeBucketCounts:
    """Bucket open critical+high findings by age since `sla_started_at`.

    "Open" here uses `Finding.status.in_(open_set)` — the same definition used
    by `sla_compliance_pct` directly above. The fancier event-replay path in
    `_open_critical_count_at` exists to give an HONEST `7d-ago` snapshot for
    WoW; for the *current* age distribution the column-status definition is
    correct (and an order of magnitude cheaper).

    Bucket boundaries are inclusive of the upper bound: `(0, 7]`, `(7, 30]`,
    `(30, 90]`, `(90, ∞)`. A finding whose anchor is exactly 7d ago lands in
    `lte_7d`. The largest bucket dominates visually on the rendered bar.
    """
    q = apply_finding_scope(select(_SLA_ANCHOR.label("anchor")), user).where(
        Finding.status.in_(_open_status_values()),
        Finding.severity.in_((Severity.critical, Severity.high)),
    )
    if scope:
        if scope.teams:
            q = q.where(Finding.owner_team.in_(scope.teams))
        if scope.repo_asset_ids:
            q = q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if sources:
        q = q.where(Finding.source.in_(sources))
    q = _apply_wiz_issues_only_filter(q, enabled=platform_wiz_issues_only)
    anchors = [row[0] for row in session.execute(q).all() if row[0] is not None]

    lte_7d = lte_30d = lte_90d = gt_90d = 0
    seven = 7 * 86_400
    thirty = 30 * 86_400
    ninety = 90 * 86_400
    for anchor in anchors:
        age = (now - anchor).total_seconds()
        if age <= seven:
            lte_7d += 1
        elif age <= thirty:
            lte_30d += 1
        elif age <= ninety:
            lte_90d += 1
        else:
            gt_90d += 1
    return AgeBucketCounts(
        lte_7d=lte_7d, lte_30d=lte_30d, lte_90d=lte_90d, gt_90d=gt_90d
    )


def _oldest_open_critical_age_seconds(
    session: Session,
    user: UserContext,
    now: datetime,
    scope: ResolvedScope | None,
    sources: list[str] | None = None,
    *,
    platform_wiz_issues_only: bool = False,
) -> int | None:
    """Max age of any open critical in scope. Null when the scope has none.

    Uses status-based open-ness for consistency with `_age_buckets_*` and the
    SLA-compliance pipeline. The number is rendered as a single KPI card on
    /executive — "147 days" is the kind of figure that forces an exec
    triage conversation, so the call is deliberately separated from the
    event-replay path that powers WoW.
    """
    q = apply_finding_scope(select(func.min(_SLA_ANCHOR)), user).where(
        Finding.status.in_(_open_status_values()),
        Finding.severity == Severity.critical,
    )
    if scope:
        if scope.teams:
            q = q.where(Finding.owner_team.in_(scope.teams))
        if scope.repo_asset_ids:
            q = q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if sources:
        q = q.where(Finding.source.in_(sources))
    q = _apply_wiz_issues_only_filter(q, enabled=platform_wiz_issues_only)
    anchor = session.execute(q).scalar_one_or_none()
    if anchor is None:
        return None
    return int((now - anchor).total_seconds())


@router.get("/summary", response_model=MetricsSummaryResponse)
def metrics_summary(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    team: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional team filter applied AFTER RBAC scoping. "
                "Repeat the param for union semantics — e.g. pass every team key "
                "in an executive pillar to scope the KPI strip to that pillar "
                "(`?team=order&team=offer&team=pc&...` for the Product pillar's "
                "summary card on /executive). Omitted = org-wide (legacy "
                "behaviour)."
            ),
        ),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    source_in: Annotated[
        list[str] | None,
        Query(
            alias="source",
            description="Filter by source. Repeat for union semantics.",
        ),
    ] = None,
    platform_wiz_issues_only: Annotated[
        bool,
        Query(
            description=(
                "When true, Wiz rows owned by platform teams count only "
                "wiz_category=issue in burn-down, age buckets, and KPI counts. "
                "See `/metrics/top-teams`."
            ),
        ),
    ] = False,
) -> MetricsSummaryResponse:
    scope = _resolve_request_scope(
        team=team,
        executive_pillar=executive_pillar,
        pillar=pillar,
        jira_project=jira_project,
        application=application,
        service=service,
        server=server,
        repo=repo,
    )
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    sla = get_policy_cache().get_sla()

    # Observation window in scope — `MIN(first_seen_at)` after RBAC + ?team=.
    # Drives the nullability of WoW delta and the frontend hint on MTTR.
    obs_q = apply_finding_scope(select(func.min(Finding.first_seen_at)), user)
    if scope.teams:
        obs_q = obs_q.where(Finding.owner_team.in_(scope.teams))
    if scope.repo_asset_ids:
        obs_q = obs_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        obs_q = obs_q.where(Finding.source.in_(source_in))
    observed_since: datetime | None = session.execute(obs_q).scalar_one_or_none()

    open_criticals_now = _open_critical_count_at(
        session,
        user,
        now,
        scope=scope,
        sources=source_in,
        platform_wiz_issues_only=platform_wiz_issues_only,
    )
    wow_delta: int | None
    if observed_since is None or (now - observed_since) < timedelta(days=7):
        # Frontend renders "history < 7d" instead of a misleading "+0 WoW".
        wow_delta = None
    else:
        open_criticals_then = _open_critical_count_at(
            session,
            user,
            week_ago,
            scope=scope,
            sources=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
        wow_delta = open_criticals_now - open_criticals_then

    open_q = apply_finding_scope(select(Finding), user).where(
        Finding.status.in_(_open_status_values())
    )
    if scope.teams:
        open_q = open_q.where(Finding.owner_team.in_(scope.teams))
    if scope.repo_asset_ids:
        open_q = open_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        open_q = open_q.where(Finding.source.in_(source_in))
    open_q = _apply_wiz_issues_only_filter(
        open_q, enabled=platform_wiz_issues_only
    )
    open_findings = list(session.scalars(open_q))
    if open_findings:
        breached = sum(
            1
            for f in open_findings
            if is_breached(sla, f.severity, f.status, f.sla_started_at, now)
        )
        sla_compliance_pct = round(100.0 * (1 - breached / len(open_findings)), 1)
    else:
        sla_compliance_pct = 100.0

    thirty_days_ago = now - timedelta(days=30)
    crit_in_scope_q = apply_finding_scope(
        select(Finding.id, _SLA_ANCHOR.label("anchor")), user
    ).where(Finding.severity == Severity.critical)
    if scope.teams:
        crit_in_scope_q = crit_in_scope_q.where(Finding.owner_team.in_(scope.teams))
    if scope.repo_asset_ids:
        crit_in_scope_q = crit_in_scope_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        crit_in_scope_q = crit_in_scope_q.where(Finding.source.in_(source_in))
    crit_in_scope_q = _apply_wiz_issues_only_filter(
        crit_in_scope_q, enabled=platform_wiz_issues_only
    )
    crit_findings = list(session.execute(crit_in_scope_q).all())

    mttr_seconds: int | None = None
    if crit_findings:
        ids = [r[0] for r in crit_findings]
        anchor_by_id = {r[0]: r[1] for r in crit_findings}
        closure_rows = session.execute(
            select(FindingEvent.finding_id, func.max(FindingEvent.occurred_at))
            .where(
                FindingEvent.finding_id.in_(ids),
                FindingEvent.event_type.in_((EventType.fixed, EventType.auto_closed)),
                FindingEvent.occurred_at >= thirty_days_ago,
            )
            .group_by(FindingEvent.finding_id)
        ).all()
        if closure_rows:
            durations = [
                (closed_at - anchor_by_id[fid]).total_seconds()
                for fid, closed_at in closure_rows
            ]
            mttr_seconds = int(statistics.median(durations))

    seen_sources = {
        row[0] for row in session.execute(select(ProcessedPayload.source).distinct())
    }
    expected_total = 7  # Tier 1 sources from design §3
    scanners_active = len(seen_sources)

    # Inflow / outflow. Honesty rule: when in-scope observation
    # history is younger than the window we're asking about, null the count
    # rather than show "0 closures" — the count is structurally undefined,
    # not zero. Same shape as `open_criticals_wow_delta` above.
    obs_age = (now - observed_since) if observed_since is not None else None
    has_7d_history = obs_age is not None and obs_age >= timedelta(days=7)
    has_30d_history = obs_age is not None and obs_age >= timedelta(days=30)
    new_crit_7d = (
        _critical_event_count(
            session,
            user,
            since=week_ago,
            event_types=_INFLOW_EVENTS,
            scope=scope,
            sources=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
        if has_7d_history
        else None
    )
    closed_crit_7d = (
        _critical_event_count(
            session,
            user,
            since=week_ago,
            event_types=_OUTFLOW_EVENTS,
            scope=scope,
            sources=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
        if has_7d_history
        else None
    )
    new_crit_30d = (
        _critical_event_count(
            session,
            user,
            since=thirty_days_ago,
            event_types=_INFLOW_EVENTS,
            scope=scope,
            sources=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
        if has_30d_history
        else None
    )
    closed_crit_30d = (
        _critical_event_count(
            session,
            user,
            since=thirty_days_ago,
            event_types=_OUTFLOW_EVENTS,
            scope=scope,
            sources=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
        if has_30d_history
        else None
    )

    age_buckets = _age_buckets_open_crit_high(
        session,
        user,
        now,
        scope=scope,
        sources=source_in,
        platform_wiz_issues_only=platform_wiz_issues_only,
    )
    oldest_crit = _oldest_open_critical_age_seconds(
        session,
        user,
        now,
        scope=scope,
        sources=source_in,
        platform_wiz_issues_only=platform_wiz_issues_only,
    )

    return MetricsSummaryResponse(
        open_criticals=open_criticals_now,
        open_criticals_wow_delta=wow_delta,
        sla_compliance_pct=sla_compliance_pct,
        mttr_critical_30d_seconds=mttr_seconds,
        observed_since=observed_since,
        scanners_active=scanners_active,
        scanners_total=expected_total,
        new_critical_7d=new_crit_7d,
        closed_critical_7d=closed_crit_7d,
        new_critical_30d=new_crit_30d,
        closed_critical_30d=closed_crit_30d,
        age_buckets_open_crit_high=age_buckets,
        oldest_open_critical_age_seconds=oldest_crit,
    )


def _scoped_trend_open_findings_query(
    user: UserContext,
    scope: ResolvedScope,
    *,
    platform_pillar: str | None,
    pillar_wiz_teams: frozenset[str],
    asset: str | None,
    source_in: list[str] | None,
    platform_wiz_issues_only: bool = False,
):
    """Open findings query with the same narrowing as `/metrics/security-posture`."""
    open_q = apply_finding_scope(select(Finding.severity), user).where(
        Finding.status.in_(_open_status_values())
    )
    if platform_pillar:
        open_q = apply_platform_pillar_asymmetric_scope(
            open_q, platform_pillar, pillar_wiz_teams
        )
    else:
        open_q = apply_finding_team_scope(
            open_q, scope.teams, platform_pillar=platform_pillar
        )
    if scope.repo_asset_ids:
        open_q = open_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        open_q = open_q.where(Finding.source.in_(source_in))
    if asset:
        open_q = open_q.where(Finding.asset_display.ilike(f"%{asset}%"))
    elif scope.asset_terms:
        open_q = open_q.where(
            Finding.asset_display.ilike(f"%{scope.asset_terms[0]}%")
        )
    return _apply_wiz_issues_only_filter(
        open_q,
        enabled=platform_wiz_issues_only,
        platform_pillar=platform_pillar,
    )


def _overlay_live_today_on_trend_points(
    session: Session,
    user: UserContext,
    points: list[TrendPoint],
    *,
    scope: ResolvedScope,
    platform_pillar: str | None,
    pillar_wiz_teams: frozenset[str],
    asset: str | None,
    source_in: list[str] | None,
    platform_wiz_issues_only: bool = False,
) -> list[TrendPoint]:
    """Replace today's rollup slice with live open counts so the chart matches the KPI boxes."""
    today = datetime.now(UTC).date()
    rows = session.scalars(
        _scoped_trend_open_findings_query(
            user,
            scope,
            platform_pillar=platform_pillar,
            pillar_wiz_teams=pillar_wiz_teams,
            asset=asset,
            source_in=source_in,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )
    ).all()
    per_severity: dict[Severity, int] = dict.fromkeys(Severity, 0)
    for sev in rows:
        per_severity[sev] += 1

    out = [p for p in points if p.date != today]
    for sev, count in per_severity.items():
        if count > 0:
            out.append(TrendPoint(date=today, severity=sev, open_count=count))
    out.sort(key=lambda p: (p.date, p.severity.value))
    return out


def _metrics_trend_event_replay(
    session: Session,
    user: UserContext,
    *,
    days: int,
    team: list[str] | None,
    asset: str | None,
    repo_asset_ids: tuple[str, ...] = (),
    source_in: list[str] | None = None,
    platform_pillar: str | None = None,
    pillar_wiz_teams: frozenset[str] | None = None,
    platform_wiz_issues_only: bool = False,
) -> MetricsTrendResponse:
    """Per-day event replay — used when `?asset=` or `?platform_pillar=` is set."""
    now = datetime.now(UTC)
    start = now - timedelta(days=days - 1)

    in_scope = apply_finding_scope(
        select(Finding.id, Finding.severity, _SLA_ANCHOR.label("anchor")), user
    )
    if platform_pillar:
        in_scope = apply_platform_pillar_asymmetric_scope(
            in_scope,
            platform_pillar,
            pillar_wiz_teams or frozenset(),
        )
    elif team:
        in_scope = in_scope.where(Finding.owner_team.in_(team))
    if repo_asset_ids:
        in_scope = in_scope.where(Finding.asset_id.in_(repo_asset_ids))
    if source_in:
        in_scope = in_scope.where(Finding.source.in_(source_in))
    if asset:
        in_scope = in_scope.where(Finding.asset_display.ilike(f"%{asset}%"))
    in_scope = _apply_wiz_issues_only_filter(
        in_scope,
        enabled=platform_wiz_issues_only,
        platform_pillar=platform_pillar,
    )
    findings = [
        {"id": fid, "severity": sev, "anchor": anchor}
        for fid, sev, anchor in session.execute(in_scope).all()
    ]
    if not findings:
        return MetricsTrendResponse(window_days=days, points=[])

    finding_ids = [f["id"] for f in findings]
    closing_types = (EventType.fixed, EventType.auto_closed, EventType.suppressed)
    close_events = session.execute(
        select(FindingEvent.finding_id, FindingEvent.occurred_at, FindingEvent.event_type)
        .where(
            FindingEvent.finding_id.in_(finding_ids),
            FindingEvent.event_type.in_((*closing_types, EventType.reopened)),
        )
        .order_by(FindingEvent.occurred_at)
    ).all()

    events_by_finding: dict[UUID, list[tuple[datetime, EventType]]] = {}
    for fid, occurred_at, event_type in close_events:
        events_by_finding.setdefault(fid, []).append((occurred_at, event_type))

    points: list[TrendPoint] = []
    for offset in range(days):
        asof_date = (start + timedelta(days=offset)).date()
        asof_dt = datetime.combine(asof_date, datetime.max.time(), tzinfo=UTC)
        per_severity: dict[Severity, int] = dict.fromkeys(Severity, 0)
        for f in findings:
            if f["anchor"] > asof_dt:
                continue
            history = [(t, et) for t, et in events_by_finding.get(f["id"], []) if t <= asof_dt]
            is_closed = False
            for _occurred_at, event_type in history:
                is_closed = event_type in closing_types
            if not is_closed:
                per_severity[f["severity"]] += 1

        for sev, count in per_severity.items():
            if count == 0:
                continue
            points.append(TrendPoint(date=asof_date, severity=sev, open_count=count))

    return MetricsTrendResponse(window_days=days, points=points)


@router.get("/trend", response_model=MetricsTrendResponse)
def metrics_trend(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    days: Annotated[int, Query(ge=1, le=365)] = 90,
    team: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional team filter applied AFTER RBAC scoping. "
                "Repeat the param to filter on multiple teams (union semantics) — "
                "e.g. `?team=io-platform-eng&team=product-platform` for the "
                "Platform view."
            ),
        ),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    asset: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=(
                "Case-insensitive substring on `asset_display` (mirrors the "
                "/findings ?asset filter). Used by the Developer view's "
                "click-to-select on a service row ( "
                "2026-05-18) — clicking Orders API scopes the trend chart to "
                "`ExampleOrg.Commerce.Orders.API`'s findings."
            ),
        ),
    ] = None,
    source_in: Annotated[
        list[str] | None,
        Query(
            alias="source",
            description="Filter by source. Repeat for union semantics.",
        ),
    ] = None,
    platform_pillar: Annotated[
        str | None,
        Query(
            description=(
                "Platform view tab (product / retail / io). When set, trend "
                "uses the same asymmetric per-source team scope as "
                "/metrics/security-posture, via event replay."
            ),
        ),
    ] = None,
    platform_wiz_issues_only: Annotated[
        bool,
        Query(
            description=(
                "When true, Wiz rows owned by platform teams count only "
                "wiz_category=issue. Uses event replay so the chart matches "
                "exec pillar scope. See `/metrics/top-teams`."
            ),
        ),
    ] = False,
) -> MetricsTrendResponse:
    scope = _resolve_request_scope(
        team=team,
        executive_pillar=executive_pillar,
        pillar=pillar,
        jira_project=jira_project,
        application=application,
        service=service,
        server=server,
        repo=repo,
    )
    effective_asset = asset
    if not effective_asset and scope.asset_terms:
        effective_asset = scope.asset_terms[0]

    pillar_wiz_teams: frozenset[str] = frozenset()
    if platform_pillar:
        pillar_wiz_teams = get_config_cache().get_component_registry().wiz_teams_for_pillar.get(
            platform_pillar, frozenset()
        )

    if (
        effective_asset
        or scope.repo_asset_ids
        or platform_pillar
        or platform_wiz_issues_only
    ):
        return _metrics_trend_event_replay(
            session,
            user,
            days=days,
            team=list(scope.teams) if scope.teams else None,
            asset=effective_asset,
            repo_asset_ids=scope.repo_asset_ids,
            source_in=source_in,
            platform_pillar=platform_pillar,
            pillar_wiz_teams=pillar_wiz_teams,
            platform_wiz_issues_only=platform_wiz_issues_only,
        )

    now = datetime.now(UTC)
    start_date = (now - timedelta(days=days - 1)).date()
    end_date = now.date()

    q = (
        select(
            DailyMetric.date,
            DailyMetric.severity,
            func.sum(DailyMetric.open_count).label("open_count"),
        )
        .where(
            DailyMetric.date >= start_date,
            DailyMetric.date <= end_date,
            DailyMetric.source.notin_(ADMIN_ONLY_SOURCES),
        )
        .group_by(DailyMetric.date, DailyMetric.severity)
        .order_by(DailyMetric.date, DailyMetric.severity)
    )
    q = apply_daily_metric_team_scope(q, scope.teams, platform_pillar=platform_pillar)
    if source_in:
        q = q.where(DailyMetric.source.in_(source_in))

    rows = session.execute(q).all()
    points = [
        TrendPoint(date=row[0], severity=row[1], open_count=int(row[2] or 0))
        for row in rows
        if int(row[2] or 0) > 0
    ]
    points = _overlay_live_today_on_trend_points(
        session,
        user,
        points,
        scope=scope,
        platform_pillar=platform_pillar,
        pillar_wiz_teams=pillar_wiz_teams,
        asset=effective_asset,
        source_in=source_in,
    )
    return MetricsTrendResponse(window_days=days, points=points)


@router.get("/top-teams", response_model=list[TopTeamPoint])
def metrics_top_teams(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    team: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional team filter applied AFTER RBAC scoping. "
                "Repeat the param for union semantics — used by the executive "
                "view's per-pillar offender list to bound the ranking to the "
                "selected pillar's team set (e.g. all 17 Product sub-team keys). "
                "Omitted = org-wide ranking (legacy behaviour). Cap is 50 so a "
                "single pillar can render its full ranked list rather than a "
                "top-5; 50 comfortably covers the largest current pillar (Product "
                "has ~17 sub-teams in `executive-view mapping.md`)."
            ),
        ),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    platform_wiz_issues_only: Annotated[
        bool,
        Query(
            description=(
                "When true, Wiz rows owned by platform teams "
                "(product-platform, platform-retail, io-platform-eng) count "
                "only wiz_category=issue. Used by the executive detail offender "
                "list so CPE/IPE Wiz totals match Wiz Issues, not cloud_config "
                "or vulnerability findings."
            ),
        ),
    ] = False,
) -> list[TopTeamPoint]:
    scope = _resolve_request_scope(
        team=team,
        executive_pillar=executive_pillar,
        pillar=pillar,
        jira_project=jira_project,
        application=application,
        service=service,
        server=server,
        repo=repo,
    )
    """Top teams by open critical+high count.

    Excludes `owner_team='unowned'` — a "team leaderboard" surfacing rows
    attributed to "no team" turns the chart into a triage queue and confuses
    its meaning at the executive level. Unowned findings remain fully visible
    on the Admin view (which is where they belong — adding an `ownership.yaml`
    entry is the resolution path). The Executive view's `summary.open_criticals`
    KPI continues to include unowned in its total so the headline number stays
    honest.

    : the optional `?team=` multi-filter scopes the ranking to a
    pillar's team set. The unowned exclusion still applies post-filter — even
    if a caller explicitly passes `?team=unowned`, the row is dropped.

    The response splits the count into `open_criticals` and `open_highs` (with
    `open_count` retained as their sum) so the offender list on /executive can
    render "5 critical · 12 high" rather than the conflated total — the user
    needs to distinguish a team carrying 5 criticals from a team carrying 5
    highs even when the totals match.
    """
    crit_sum = func.sum(
        case((Finding.severity == Severity.critical, 1), else_=0)
    ).label("crit")
    high_sum = func.sum(
        case((Finding.severity == Severity.high, 1), else_=0)
    ).label("high")
    base = apply_finding_scope(
        select(Finding.owner_team, crit_sum, high_sum),
        user,
    ).where(
        Finding.status.in_(_open_status_values()),
        Finding.severity.in_((Severity.critical, Severity.high)),
        Finding.owner_team != UNOWNED_TEAM,
    )
    if scope.teams:
        base = base.where(Finding.owner_team.in_(scope.teams))
    if scope.repo_asset_ids:
        base = base.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if platform_wiz_issues_only:
        base = _apply_platform_wiz_issues_only(base)
    rows = session.execute(
        base.group_by(Finding.owner_team)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [
        TopTeamPoint(
            team=team_key,
            open_criticals=int(crit or 0),
            open_highs=int(high or 0),
            open_count=int((crit or 0) + (high or 0)),
        )
        for team_key, crit, high in rows
    ]


def _compute_source_rating(
    source: str, open_criticals: int, open_highs: int, open_mediums: int
) -> SourceRating:
    """Per-source A-D grade. First matching condition wins.

    The ladders below are calibrated against four principles:
      P1. A = "achievable today by a healthy team" — zero crit AND zero high.
          (Pentest A also requires zero medium.)
      P2. B = "realistic working state for an engaged team" — small backlog,
          stable across normal weekly noise.
      P3. C = "real backlog forming, escalation conversation needed".
      P4. D = "stop adding new work, drain the queue".

    Sonar and Dependabot share a ladder: both are continuous high-volume scans,
    a single finding is often noise, the rating only flips on persistent
    backlog. Pentest diverges deliberately — findings are rare, manual, and
    each one is a deliberate professional alarm, so a single critical is
    already C and ≥2 criticals is D.

    To change a threshold:
      1. Edit the ladder below.
      2. Update the boundary tests (test_*_rating_*_band*).
    """
    if source in ("sonarcloud", "dependabot", "wiz"):
        if open_criticals == 0 and open_highs == 0:
            grade, why = "A", "No critical or high findings"
        elif open_criticals <= 2 and open_highs <= 10:
            grade, why = "B", "Small backlog (≤2 critical, ≤10 high)"
        elif open_criticals <= 10 and open_highs <= 30:
            grade, why = "C", "Real backlog (≤10 critical, ≤30 high)"
        else:
            grade, why = "D", "Severe backlog (>10 critical or >30 high)"
    elif source == "pentest":
        if open_criticals == 0 and open_highs == 0 and open_mediums == 0:
            grade, why = "A", "No open pentest findings"
        elif open_criticals == 0 and open_highs == 0 and open_mediums <= 2:
            grade, why = "B", "Low-impact only (≤2 medium, no critical/high)"
        elif open_criticals >= 2 or open_highs >= 3:
            grade, why = "D", "≥2 critical or ≥3 high"
        else:
            grade, why = "C", "1 critical or 1-2 high or ≥3 medium"
    else:
        # Defensive: a future source registered without a ladder lands at A so
        # it's visibly wrong (zero counts shown) rather than crash-on-render.
        grade, why = "A", f"no rating ladder defined for source '{source}'"

    return SourceRating(
        source=source,  # type: ignore[arg-type]
        grade=grade,    # type: ignore[arg-type]
        open_criticals=open_criticals,
        open_highs=open_highs,
        open_mediums=open_mediums,
        rationale=why,
    )


def _compute_rating(
    open_criticals: int,
    open_highs: int,
    sla_compliance_pct: float,
    mttr_seconds: int | None,
) -> tuple[str, int, RatingScoreBreakdown]:
    """Map posture metrics to an A–D grade (score 0–100).

    Weights:
      - Criticals (0–35): heavily penalised — each critical deducts 7 pts.
      - SLA compliance (0–35): percentage scaled linearly.
      - MTTR for criticals (0–15): tiered by days; neutral (10) when no closures yet.
      - Highs (0–15): each high deducts 1 pt.

    Thresholds: A ≥ 85, B ≥ 65, C ≥ 45, D < 45.
    """
    criticals_score = max(0, 35 - open_criticals * 7)
    sla_score = round(sla_compliance_pct * 0.35)
    if mttr_seconds is None:
        mttr_score = 10  # no closures yet — treat as neutral
    elif mttr_seconds <= 7 * 86_400:
        mttr_score = 15
    elif mttr_seconds <= 14 * 86_400:
        mttr_score = 11
    elif mttr_seconds <= 30 * 86_400:
        mttr_score = 7
    else:
        mttr_score = 3
    highs_score = max(0, 15 - open_highs)

    score = criticals_score + sla_score + mttr_score + highs_score
    if score >= 85:
        grade = "A"
    elif score >= 65:
        grade = "B"
    elif score >= 45:
        grade = "C"
    else:
        grade = "D"

    return grade, score, RatingScoreBreakdown(
        criticals_score=criticals_score,
        sla_score=sla_score,
        mttr_score=mttr_score,
        highs_score=highs_score,
    )


@router.get("/security-posture", response_model=SecurityPostureResponse)
def security_posture(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    team: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional team filter applied AFTER RBAC scoping. "
                "Repeat the param for union semantics across multiple teams "
                "(used by the Platform view to span io-platform-eng + "
                "product-platform since their 2026-05-15 split, and by the "
                "Developer view's click-to-select on an application or team "
                "row per the 2026-05-18 dev-view rework)."
            ),
        ),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    asset: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=(
                "Case-insensitive substring on `asset_display` (mirrors the "
                "/findings ?asset filter). The Developer view sends this when "
                "the user clicks a *service* row — narrows every card on the "
                "page to that one service's findings, including the 4-up "
                "source rating row and the SLA totals."
            ),
        ),
    ] = None,
    source_in: Annotated[
        list[str] | None,
        Query(
            alias="source",
            description="Filter by source. Repeat for union semantics.",
        ),
    ] = None,
    platform_pillar: Annotated[
        str | None,
        Query(
            description=(
                "Platform view tab (product / retail / io). When set, per-source "
                "ratings use asymmetric team narrowing: Sonar+Dependabot+Pen.Test "
                "use the platform code team for the tab; Wiz uses all registry teams "
                "with a wiz_service in that pillar. On /developer, Wiz uses "
                "the same team scope as other sources (no unowned pillar bucket)."
            ),
        ),
    ] = None,
    platform_wiz_issues_only: Annotated[
        bool,
        Query(
            description=(
                "When true, Wiz rows owned by platform teams count only "
                "wiz_category=issue in headline open counts and per-source "
                "ratings. With `platform_pillar`, non-issue categories still "
                "appear on `/platform/wiz`. See `/metrics/top-teams`."
            ),
        ),
    ] = False,
) -> SecurityPostureResponse:
    """RBAC-scoped security posture: rating, per-source counts, SLA, pentest.

    Both `?team=` and `?asset=` narrow the result AFTER RBAC scoping (so a
    developer can never escape their team-level visibility via these params).
    `?team=` is union-semantics across repeated values; `?asset=` is a single
    case-insensitive substring on `asset_display`. They compose with AND.
    Repeat `?source=` for union semantics (Platform Product tab: dependabot +
    sonarcloud only).

    Used by the Platform view (`?pillar=` on the frontend picks team + source
    sets) and by the Developer view's click-to-select on a team / service row.
    """
    now = datetime.now(UTC)
    thirty_days_ago = now - timedelta(days=30)
    sla = get_policy_cache().get_sla()
    open_statuses = _open_status_values()
    scope = _resolve_request_scope(
        team=team,
        executive_pillar=executive_pillar,
        pillar=pillar,
        jira_project=jira_project,
        application=application,
        service=service,
        server=server,
        repo=repo,
    )

    # All open findings in scope.
    open_q = apply_finding_scope(select(Finding), user).where(
        Finding.status.in_(open_statuses)
    )
    pillar_wiz_teams: frozenset[str] = frozenset()
    if platform_pillar:
        pillar_wiz_teams = get_config_cache().get_component_registry().wiz_teams_for_pillar.get(
            platform_pillar, frozenset()
        )
        open_q = apply_platform_pillar_asymmetric_scope(
            open_q, platform_pillar, pillar_wiz_teams
        )
    else:
        open_q = apply_finding_team_scope(
            open_q, scope.teams, platform_pillar=platform_pillar
        )
    if is_admin_triage_unowned_teams(team):
        cache = get_config_cache()
        open_q = apply_admin_triage_unowned_scope(
            open_q,
            cache.get_component_registry(),
            cache.get_ownership(),
        )
    if scope.repo_asset_ids:
        open_q = open_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        open_q = open_q.where(Finding.source.in_(source_in))
    if asset:
        open_q = open_q.where(Finding.asset_display.ilike(f"%{asset}%"))
    elif scope.asset_terms:
        open_q = open_q.where(Finding.asset_display.ilike(f"%{scope.asset_terms[0]}%"))
    if platform_wiz_issues_only:
        open_q = _apply_wiz_issues_only_filter(
            open_q, enabled=True, platform_pillar=platform_pillar
        )
    open_findings = list(session.scalars(open_q))

    def _count(findings: list[Finding], sev: Severity) -> int:
        return sum(1 for f in findings if f.severity == sev)

    def _breached(findings: list[Finding], sev: Severity) -> int:
        return sum(
            1
            for f in findings
            if f.severity == sev
            and is_breached(sla, f.severity, f.status, f.sla_started_at, now)
        )

    open_criticals = _count(open_findings, Severity.critical)
    open_highs = _count(open_findings, Severity.high)

    def _source_counts(source_name: str) -> SourceSeverityCount:
        src = [f for f in open_findings if f.source == source_name]
        return SourceSeverityCount(
            criticals=_count(src, Severity.critical),
            highs=_count(src, Severity.high),
        )

    sonarcloud = _source_counts("sonarcloud")
    dependabot = _source_counts("dependabot")

    criticals_out_of_sla = _breached(open_findings, Severity.critical)
    highs_out_of_sla = _breached(open_findings, Severity.high)

    pentest = [f for f in open_findings if f.source == "pentest"]
    pentest_open = SeverityBreakdown(
        critical=_count(pentest, Severity.critical),
        high=_count(pentest, Severity.high),
        medium=_count(pentest, Severity.medium),
        low=_count(pentest, Severity.low),
    )
    pentest_out_of_sla = SeverityBreakdown(
        critical=_breached(pentest, Severity.critical),
        high=_breached(pentest, Severity.high),
        medium=_breached(pentest, Severity.medium),
        low=_breached(pentest, Severity.low),
    )

    if open_findings:
        breached_total = sum(
            1
            for f in open_findings
            if is_breached(sla, f.severity, f.status, f.sla_started_at, now)
        )
        sla_compliance_pct = round(100.0 * (1 - breached_total / len(open_findings)), 1)
    else:
        sla_compliance_pct = 100.0

    # MTTR from ALL criticals in scope (including closed ones within 30d).
    all_crits_q = apply_finding_scope(
        select(Finding.id, _SLA_ANCHOR.label("anchor")), user
    ).where(Finding.severity == Severity.critical)
    if platform_pillar:
        all_crits_q = apply_platform_pillar_asymmetric_scope(
            all_crits_q, platform_pillar, pillar_wiz_teams
        )
    else:
        all_crits_q = apply_finding_team_scope(
            all_crits_q, scope.teams, platform_pillar=platform_pillar
        )
    if is_admin_triage_unowned_teams(team):
        cache = get_config_cache()
        all_crits_q = apply_admin_triage_unowned_scope(
            all_crits_q,
            cache.get_component_registry(),
            cache.get_ownership(),
        )
    if scope.repo_asset_ids:
        all_crits_q = all_crits_q.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if source_in:
        all_crits_q = all_crits_q.where(Finding.source.in_(source_in))
    if platform_wiz_issues_only:
        all_crits_q = _apply_wiz_issues_only_filter(
            all_crits_q, enabled=True, platform_pillar=platform_pillar
        )
    all_crits = list(session.execute(all_crits_q).all())
    mttr_seconds: int | None = None
    if all_crits:
        crit_ids = [r[0] for r in all_crits]
        anchor_by_id = {r[0]: r[1] for r in all_crits}
        closure_rows = session.execute(
            select(FindingEvent.finding_id, func.max(FindingEvent.occurred_at))
            .where(
                FindingEvent.finding_id.in_(crit_ids),
                FindingEvent.event_type.in_((EventType.fixed, EventType.auto_closed)),
                FindingEvent.occurred_at >= thirty_days_ago,
            )
            .group_by(FindingEvent.finding_id)
        ).all()
        if closure_rows:
            durations = [
                (closed_at - anchor_by_id[fid]).total_seconds()
                for fid, closed_at in closure_rows
                if fid in anchor_by_id
            ]
            if durations:
                mttr_seconds = int(statistics.median(durations))

    grade, score, breakdown = _compute_rating(
        open_criticals=open_criticals,
        open_highs=open_highs,
        sla_compliance_pct=sla_compliance_pct,
        mttr_seconds=mttr_seconds,
    )

    # Per-source ratings (; Wiz asymmetric narrowing ).
    if platform_pillar:
        code_teams = platform_code_teams(platform_pillar)
        wiz_teams = pillar_wiz_teams

        def _rating_findings(teams_set: frozenset[str], src: str) -> list[Finding]:
            if not teams_set and not (platform_pillar and src == "wiz"):
                return []
            q = apply_finding_scope(select(Finding), user).where(
                Finding.status.in_(open_statuses),
                Finding.source == src,
            )
            q = apply_finding_team_scope(
                q,
                teams_set,
                platform_pillar=platform_pillar if src == "wiz" else None,
            )
            if asset:
                q = q.where(Finding.asset_display.ilike(f"%{asset}%"))
            elif scope.asset_terms:
                q = q.where(Finding.asset_display.ilike(f"%{scope.asset_terms[0]}%"))
            if platform_wiz_issues_only and src == "wiz":
                q = _apply_wiz_issues_only_filter(
                    q, enabled=True, platform_pillar=platform_pillar
                )
            return list(session.scalars(q))

        def _rating_for(src: str, teams_set: frozenset[str]) -> SourceRating:
            scoped = _rating_findings(teams_set, src)
            return _compute_source_rating(
                src,
                _count(scoped, Severity.critical),
                _count(scoped, Severity.high),
                sum(1 for f in scoped if f.severity == Severity.medium),
            )

        if is_threat_intel_pillar(platform_pillar):
            source_ratings = [_rating_for("wiz", frozenset())]
        else:
            source_ratings = [
                _rating_for("sonarcloud", code_teams),
                _rating_for("dependabot", code_teams),
                _rating_for("wiz", wiz_teams),
                _rating_for("pentest", code_teams),
            ]
    else:
        source_ratings = [
            _compute_source_rating(
                "sonarcloud",
                sonarcloud.criticals,
                sonarcloud.highs,
                sum(
                    1
                    for f in open_findings
                    if f.source == "sonarcloud" and f.severity == Severity.medium
                ),
            ),
            _compute_source_rating(
                "dependabot",
                dependabot.criticals,
                dependabot.highs,
                sum(
                    1
                    for f in open_findings
                    if f.source == "dependabot" and f.severity == Severity.medium
                ),
            ),
            _compute_source_rating(
                "pentest",
                pentest_open.critical,
                pentest_open.high,
                pentest_open.medium,
            ),
            _compute_source_rating(
                "wiz",
                sum(
                    1
                    for f in open_findings
                    if f.source == "wiz" and f.severity == Severity.critical
                ),
                sum(
                    1
                    for f in open_findings
                    if f.source == "wiz" and f.severity == Severity.high
                ),
                sum(
                    1
                    for f in open_findings
                    if f.source == "wiz" and f.severity == Severity.medium
                ),
            ),
        ]

    return SecurityPostureResponse(
        rating=grade,
        score=score,
        score_breakdown=breakdown,
        open_criticals=open_criticals,
        open_highs=open_highs,
        sonarcloud=sonarcloud,
        dependabot=dependabot,
        criticals_out_of_sla=criticals_out_of_sla,
        highs_out_of_sla=highs_out_of_sla,
        pentest_open=pentest_open,
        pentest_out_of_sla=pentest_out_of_sla,
        source_ratings=source_ratings,
    )


@router.get("/top-services", response_model=list[TopAssetPoint])
def metrics_top_services(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    team: Annotated[
        list[str] | None,
        Query(
            description=(
                "Optional team filter applied AFTER RBAC scoping. Repeat for "
                "union semantics — used by the executive view's per-pillar "
                "offender list (By service mode) to scope ranking to the "
                "selected pillar's team set."
            ),
        ),
    ] = None,
    executive_pillar: Annotated[str | None, Query()] = None,
    pillar: Annotated[str | None, Query()] = None,
    jira_project: Annotated[str | None, Query()] = None,
    application: Annotated[str | None, Query()] = None,
    service: Annotated[str | None, Query()] = None,
    server: Annotated[str | None, Query()] = None,
    repo: Annotated[str | None, Query()] = None,
    platform_wiz_issues_only: Annotated[
        bool,
        Query(
            description=(
                "When true, Wiz rows owned by platform teams count only "
                "wiz_category=issue. See `/metrics/top-teams`."
            ),
        ),
    ] = False,
) -> list[TopAssetPoint]:
    scope = _resolve_request_scope(
        team=team,
        executive_pillar=executive_pillar,
        pillar=pillar,
        jira_project=jira_project,
        application=application,
        service=service,
        server=server,
        repo=repo,
    )
    """Top assets (repos / Sonar projects) by open critical+high count.

    Sister endpoint to `/metrics/top-teams`, one rung finer-grained. Same
    `unowned` exclusion, same `?team=` semantics, but groups by
    `(asset_display, owner_team)` so the executive view can rank services
    within a pillar.

    The cap is 200 because some assets (e.g. the 4 Sonar projects making up
    `product-go-bundle`) collapse to a single service downstream, so the
    frontend may need to read more rows than its target display count to
    cover every service in a pillar.

    Per-severity split (`open_criticals` / `open_highs`) mirrors the
    /top-teams change — the offender list expands a team row into its
    services and the per-service breakdown needs to be queryable without a
    second `/findings` round trip.
    """
    crit_sum = func.sum(
        case((Finding.severity == Severity.critical, 1), else_=0)
    ).label("crit")
    high_sum = func.sum(
        case((Finding.severity == Severity.high, 1), else_=0)
    ).label("high")
    base = apply_finding_scope(
        select(
            Finding.asset_display,
            Finding.owner_team,
            crit_sum,
            high_sum,
        ),
        user,
    ).where(
        Finding.status.in_(_open_status_values()),
        Finding.severity.in_((Severity.critical, Severity.high)),
        Finding.owner_team != UNOWNED_TEAM,
    )
    if scope.teams:
        base = base.where(Finding.owner_team.in_(scope.teams))
    if scope.repo_asset_ids:
        base = base.where(Finding.asset_id.in_(scope.repo_asset_ids))
    if platform_wiz_issues_only:
        base = _apply_platform_wiz_issues_only(base)
    rows = session.execute(
        base.group_by(Finding.asset_display, Finding.owner_team)
        .order_by(func.count().desc())
        .limit(limit)
    ).all()
    return [
        TopAssetPoint(
            asset_display=asset,
            owner_team=owner,
            open_criticals=int(crit or 0),
            open_highs=int(high or 0),
            open_count=int((crit or 0) + (high or 0)),
        )
        for asset, owner, crit, high in rows
    ]


@router.get("/sla-breaches", response_model=list[SlaBreachItem])
def metrics_sla_breaches(
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[SlaBreachItem]:
    """Worst SLA breaches by age, surfaced on the Executive view.

    Excludes `owner_team='unowned'` for the same reason as `/top-teams` — a
    breach leaderboard at the exec level should be team-attributable; an
    unowned breach is admin's triage signal, surfaced on /admin. The
    Executive view's `summary.sla_compliance_pct` KPI continues to include
    unowned in its denominator, so the headline number stays honest.
    """
    now = datetime.now(UTC)
    sla = get_policy_cache().get_sla()
    base = (
        apply_finding_scope(select(Finding), user)
        .where(Finding.status.in_(_open_status_values()))
        .where(Finding.owner_team != UNOWNED_TEAM)
    )
    open_findings = list(session.scalars(base.order_by(_SLA_ANCHOR)))
    breached = [
        f for f in open_findings if is_breached(sla, f.severity, f.status, f.sla_started_at, now)
    ]
    breached.sort(key=lambda f: f.sla_started_at)
    return [
        SlaBreachItem(
            finding_id=f.id,
            title=f.title,
            severity=f.severity,
            owner_team=f.owner_team,
            asset_display=f.asset_display,
            age_days=age_seconds(f.sla_started_at, now) / 86_400,
        )
        for f in breached[:limit]
    ]
