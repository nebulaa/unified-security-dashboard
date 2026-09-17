"""Response models for the API. All inbound data uses query/path parameters."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import EventType, Severity, Status


class FindingSummary(BaseModel):
    id: UUID
    source: str
    native_id: str
    title: str
    severity: Severity
    status: Status
    cve_id: str | None
    asset_display: str
    owner_team: str
    first_seen_at: datetime  # when our system first ingested it
    last_seen_at: datetime
    upstream_created_at: datetime | None  # source-system creation time
    reopened_at: datetime | None  # set on auto_closed -> open
    sla_started_at: datetime  # the actual age + SLA anchor
    age_days: float
    sla_breached: bool
    wiz_category: str | None = None
    upstream_url: str | None = None


class WizServiceGroup(BaseModel):
    wiz_service: str
    service_label: str
    owner_team: str
    application: str | None = None
    count: int
    items: list[FindingSummary]


class WizTitleGroup(BaseModel):
    """Cloud misconfigs sharing the same Wiz rule / control title."""

    title: str
    count: int
    items: list[FindingSummary]


class WizCategoryGroup(BaseModel):
    wiz_category: str
    label: str
    count: int
    items: list[FindingSummary]
    service_groups: list[WizServiceGroup] | None = None
    title_groups: list[WizTitleGroup] | None = None


class WizFindingsByCategoryResponse(BaseModel):
    total: int
    categories: list[WizCategoryGroup]


class FindingListResponse(BaseModel):
    items: list[FindingSummary]
    total: int
    limit: int
    offset: int


class FindingEventResponse(BaseModel):
    event_type: EventType
    from_value: str | None
    to_value: str
    occurred_at: datetime
    actor: str
    reason: str | None


class FindingDetail(FindingSummary):
    description: str
    cwe_id: str | None
    asset_id: str
    asset_type: str
    asset_root: str
    correlation_group_id: UUID | None
    consecutive_misses: int
    raw_payload_uri: str
    tags: list[str]
    events: list[FindingEventResponse]


class AgeBucketCounts(BaseModel):
    """Open critical+high findings bucketed by age (since `sla_started_at`).

    Powers the executive view's "what's been ignored?" horizontal stacked bar.
    Buckets are half-open intervals: `lte_7d` covers `(0, 7]` days, `gt_90d`
    covers `(90, ∞)` days, etc. The frontend renders the bar in this exact
    order so older buckets visually dominate.
    """

    lte_7d: int
    lte_30d: int
    lte_90d: int
    gt_90d: int


class MetricsSummaryResponse(BaseModel):
    open_criticals: int
    # Nullable so the frontend can distinguish "we observed the same count 7d
    # ago" (delta = 0) from "we only just started observing" (delta = null).
    # See `metrics_summary` in `routes_metrics.py` for the cutoff: we null this
    # when the earliest in-scope `first_seen_at` is < 7d ago, because the WoW
    # math relies on `_SLA_ANCHOR` (upstream_created_at) for the "7d ago"
    # snapshot and that would otherwise retroactively project every Sonar
    # finding (whose upstream_created_at can be years old) as "was open then",
    # giving a confidently-wrong +0 WoW on a fresh DB.
    open_criticals_wow_delta: int | None
    sla_compliance_pct: float
    mttr_critical_30d_seconds: int | None
    # Earliest `first_seen_at` across findings in the response's scope (after
    # RBAC + ?team= filter). Null when the scope is empty. The frontend uses
    # this to render history-aware hints on the WoW + MTTR KPIs — "history < 7d"
    # rather than "+0 WoW", "history < 30d" rather than "no closures yet".
    observed_since: datetime | None
    scanners_active: int
    scanners_total: int

    # ---- Executive-view extras --
    # Inflow / outflow counts of CRITICAL findings over the trailing 7d and 30d
    # windows. "Inflow" is `discovered` ∪ `reopened` events (a re-introduced
    # critical IS new risk on the books). "Outflow" is `fixed` ∪ `auto_closed`
    # events. Both windows are nulled when the in-scope observation history
    # (`observed_since`) is younger than the window — same honesty rule that
    # already nulls `open_criticals_wow_delta` for sub-7d obs.
    new_critical_7d: int | None
    closed_critical_7d: int | None
    new_critical_30d: int | None
    closed_critical_30d: int | None

    # Age distribution of open critical+high findings — never null (zeros when
    # scope is empty). Drives the exec view's aging-buckets bar chart.
    age_buckets_open_crit_high: AgeBucketCounts

    # Max `now - sla_started_at` across open criticals in scope. Null when
    # there are no open criticals — the frontend renders "—" rather than 0.
    # Used by the exec view's "Oldest open critical" KPI card; the number is
    # the strongest forcing function for triage conversations at exec level.
    oldest_open_critical_age_seconds: int | None


class TrendPoint(BaseModel):
    date: date
    severity: Severity
    open_count: int


class MetricsTrendResponse(BaseModel):
    window_days: int
    points: list[TrendPoint]


class TopTeamPoint(BaseModel):
    team: str
    # Split per-severity so the executive offender list can render
    # "5 critical · 12 high" instead of a single conflated total. The original
    # `open_count` is kept as the sum (critical + high) so any older consumer
    # of the endpoint keeps working without a coordinated change.
    open_criticals: int
    open_highs: int
    open_count: int  # critical + high combined


class TopAssetPoint(BaseModel):
    """A single asset (repo or sonar project) ranked by open critical+high count.

    Powers the executive view's "biggest offenders — by service" view.
    `asset_display` is the raw value from `Finding.asset_display` (e.g.
    `ExampleOrg/order-service`, `ExampleOrg.Commerce.Order.API`) — the frontend resolves
    it to a service label via `component-map.ts.lookupComponent()`. Multiple
    asset_displays can collapse to the same service (e.g. the 4 Sonar projects
    that make up `product-go-bundle`), so frontend-side grouping is expected.

    `open_criticals` / `open_highs` are surfaced separately so the offender
    list can render the breakdown next to each service (and, on expand, next
    to each repo). `open_count` remains the sum for backwards-compat.
    """

    asset_display: str
    owner_team: str
    open_criticals: int
    open_highs: int
    open_count: int


class SlaBreachItem(BaseModel):
    finding_id: UUID
    title: str
    severity: Severity
    owner_team: str
    asset_display: str
    age_days: float


class ScannerHealth(BaseModel):
    source: str
    last_seen_at: datetime | None
    expected_cadence_seconds: int | None
    status: Literal["active", "stale", "dark", "no_data"]


class ScannerHealthResponse(BaseModel):
    items: list[ScannerHealth]
    active: int
    total: int


# ---------------------------------------------------------------------------
# Security posture / rating
# ---------------------------------------------------------------------------


class SourceSeverityCount(BaseModel):
    criticals: int
    highs: int


class SeverityBreakdown(BaseModel):
    critical: int
    high: int
    medium: int
    low: int


class RatingScoreBreakdown(BaseModel):
    criticals_score: int    # 0–35
    sla_score: int          # 0–35
    mttr_score: int         # 0–15
    highs_score: int        # 0–15


class SourceRating(BaseModel):
    """Per-source A–D grade for the Developer landing page.

    Distinct from `SecurityPostureResponse.rating` (the legacy composite, retained
    for the Executive view). Each per-source ladder is computed independently from
    the open critical/high (and for pentest, medium) counts in the user's RBAC scope.
    """

    source: Literal["sonarcloud", "dependabot", "pentest", "wiz"]
    grade: Literal["A", "B", "C", "D"]
    open_criticals: int
    open_highs: int
    open_mediums: int       # only meaningful for pentest; included for shape symmetry
    rationale: str          # the threshold sentence that tripped the grade


class SecurityPostureResponse(BaseModel):
    rating: Literal["A", "B", "C", "D"]
    score: int                             # 0–100
    score_breakdown: RatingScoreBreakdown

    open_criticals: int
    open_highs: int

    sonarcloud: SourceSeverityCount
    dependabot: SourceSeverityCount

    criticals_out_of_sla: int
    highs_out_of_sla: int

    pentest_open: SeverityBreakdown
    pentest_out_of_sla: SeverityBreakdown

    # Per-source A–D grades for the Developer landing page.
    # Order is fixed: sonarcloud, dependabot, pentest.
    source_ratings: list[SourceRating]
