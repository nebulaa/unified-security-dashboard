"""Coverage computation — pure functions over a snapshot plus config.

Invariants worth keeping:
  - An excepted item leaves the denominator and stays visible as a count. It is
    never silently counted as covered.
  - An empty denominator reports `na`, not 100%. A project with no EC2 estate has
    not achieved perfect VM coverage.
  - The project runtime cell is weighted by item count so it reconciles with the
    org tiles; both raw ratios travel with it in the note.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from app.coverage.config import CoverageConfig, CoverageException
from app.coverage.model import (
    CoverageReport,
    CoverageSnapshot,
    InventoryItem,
    LayerResult,
    MetricResult,
    ProjectCell,
    ProjectRow,
    Ratio,
    SecondaryResult,
    UnmappedCounts,
)
from app.coverage.spec import (
    ITEM_CLOUD_ACCOUNT,
    ITEM_REPO,
    LAYERS,
    RUNTIME_BLEND_METRICS,
    RUNTIME_COLUMN_KEY,
    MetricSpec,
    SecondarySpec,
    get_metric,
    project_columns_for,
)

RAG_GREEN = "green"
RAG_AMBER = "amber"
RAG_RED = "red"
RAG_NA = "na"

# Month-on-month delta, matching the "vs last month" figure on each tile.
DELTA_WINDOW_DAYS = 30
TREND_WINDOW_DAYS = 90
MAX_GAP_ITEMS = 50

_REQUIRED_SOURCES: dict[str, frozenset[str]] = {
    "wiz_connector": frozenset({"google", "aws", "wiz"}),
    "threat_detection": frozenset({"google", "aws", "wiz"}),
    "forensics_readiness": frozenset(
        {"google", "aws", "forensics_validation"}
    ),
    "runtime_k8s": frozenset({"google", "aws", "gke", "wiz"}),
    "runtime_vm": frozenset({"google", "aws", "gce", "wiz"}),
    "sonar": frozenset({"github", "sonar"}),
    "dependabot": frozenset({"github"}),
}

_UNIT_BY_ITEM_TYPE = {
    ITEM_CLOUD_ACCOUNT: "accounts",
    "cluster": "clusters",
    "vm": "instances",
    ITEM_REPO: "repos",
}


def _project_required_sources(
    metric_key: str, project_key: str, config: CoverageConfig
) -> frozenset[str]:
    required = _REQUIRED_SOURCES.get(metric_key, frozenset())
    project = next((p for p in config.projects if p.key == project_key), None)
    # A folder-scoped project row is explicitly GCP-only. Missing AWS auth
    # makes the organization rollup unavailable but must not hide a valid PRODUCT row.
    if project and project.cloud.folders:
        required = required - {"aws"}
    return required


def rag_for(pct: float | None, config: CoverageConfig) -> str:
    if pct is None:
        return RAG_NA
    if pct >= config.green_pct:
        return RAG_GREEN
    if pct >= config.amber_pct:
        return RAG_AMBER
    return RAG_RED


def _is_excepted(
    item: InventoryItem, metric_key: str, exceptions: Sequence[CoverageException]
) -> bool:
    return any(e.covers(item.item_type, item.item_id, metric_key) for e in exceptions)


def _select(
    items: Iterable[InventoryItem],
    *,
    item_type: str,
    in_scope_only: bool = True,
    project: str | None = None,
) -> list[InventoryItem]:
    selected = []
    for item in items:
        if item.item_type != item_type:
            continue
        if in_scope_only and not item.in_scope:
            continue
        if project is not None and project not in item.projects:
            continue
        selected.append(item)
    return selected


def _ratio(
    items: Sequence[InventoryItem],
    *,
    signal: str,
    metric_key: str,
    exceptions: Sequence[CoverageException],
) -> tuple[Ratio, list[InventoryItem]]:
    """X/Y for one metric over an already-selected item set, plus the gap list."""
    excepted_ids = {
        i.item_id for i in items if _is_excepted(i, metric_key, exceptions)
    }
    denominator = [i for i in items if i.item_id not in excepted_ids]
    covered = sum(1 for i in denominator if i.has(signal))
    gaps = [i for i in denominator if not i.has(signal)]
    ratio = Ratio(
        covered=covered,
        in_scope=len(denominator),
        excepted=len(excepted_ids),
    )
    return ratio, gaps


def _history_series(
    snapshot: CoverageSnapshot, metric_key: str, *, today: date
) -> tuple[tuple[float, ...], float | None]:
    """Sparkline points and the month-on-month delta for one metric."""
    points = sorted(
        (p for p in snapshot.history if metric_key in p.pct),
        key=lambda p: p.day,
    )
    window_start = today - timedelta(days=TREND_WINDOW_DAYS)
    trend = tuple(p.pct[metric_key] for p in points if p.day >= window_start)
    if len(points) < 2:
        return trend, None

    cutoff = today - timedelta(days=DELTA_WINDOW_DAYS)
    baseline = [p for p in points if p.day <= cutoff]
    reference = baseline[-1] if baseline else points[0]
    if reference.day > cutoff:
        # History shorter than the comparison window — a delta here would compare
        # against a few days ago while claiming to be month-on-month.
        return trend, None
    return trend, round(points[-1].pct[metric_key] - reference.pct[metric_key], 1)


def _secondary(
    snapshot: CoverageSnapshot,
    spec: SecondarySpec,
    exceptions: Sequence[CoverageException],
) -> SecondaryResult | None:
    items = _select(
        snapshot.items, item_type=spec.item_type, in_scope_only=spec.in_scope_only
    )
    if not items:
        return None
    ratio, _ = _ratio(items, signal=spec.signal, metric_key=spec.key, exceptions=exceptions)
    return SecondaryResult(key=spec.key, label=spec.label, ratio=ratio, unit=spec.unit)


def _metric_result(
    snapshot: CoverageSnapshot,
    spec: MetricSpec,
    config: CoverageConfig,
    exceptions: Sequence[CoverageException],
    *,
    today: date,
) -> MetricResult:
    items = _select(snapshot.items, item_type=spec.item_type)
    ratio, gaps = _ratio(
        items, signal=spec.signal, metric_key=spec.key, exceptions=exceptions
    )
    unavailable = tuple(
        sorted(
            _REQUIRED_SOURCES.get(spec.key, frozenset()).intersection(
                snapshot.degraded_sources
            )
        )
    )
    trend, delta = (
        ((), None)
        if unavailable
        else _history_series(snapshot, spec.key, today=today)
    )
    return MetricResult(
        key=spec.key,
        label=spec.label,
        definition=spec.definition,
        unit=spec.unit,
        ratio=ratio,
        rag=RAG_NA if unavailable else rag_for(ratio.pct, config),
        delta_pts=delta,
        trend=trend,
        gap_items=tuple(sorted(i.display for i in gaps)[:MAX_GAP_ITEMS]),
        unavailable_sources=unavailable,
        secondary=(
            _secondary(snapshot, spec.secondary, exceptions) if spec.secondary else None
        ),
    )


def _project_cell(
    snapshot: CoverageSnapshot,
    *,
    column_key: str,
    column_label: str,
    project: str,
    config: CoverageConfig,
    exceptions: Sequence[CoverageException],
) -> ProjectCell:
    if column_key == RUNTIME_COLUMN_KEY:
        return _runtime_cell(
            snapshot,
            column_label=column_label,
            project=project,
            config=config,
            exceptions=exceptions,
        )

    spec = get_metric(column_key)
    items = _select(snapshot.items, item_type=spec.item_type, project=project)
    ratio, _ = _ratio(
        items, signal=spec.signal, metric_key=spec.key, exceptions=exceptions
    )
    unavailable = tuple(
        sorted(
            _project_required_sources(spec.key, project, config).intersection(
                snapshot.degraded_sources
            )
        )
    )
    unit = _UNIT_BY_ITEM_TYPE.get(spec.item_type, "items")
    return ProjectCell(
        metric=column_key,
        label=column_label,
        ratio=ratio,
        rag=RAG_NA if unavailable else rag_for(ratio.pct, config),
        note=(
            f"incomplete: {', '.join(unavailable)}"
            if unavailable
            else f"{ratio.covered} / {ratio.in_scope} {unit}"
        ),
        unavailable_sources=unavailable,
    )


def _runtime_cell(
    snapshot: CoverageSnapshot,
    *,
    column_label: str,
    project: str,
    config: CoverageConfig,
    exceptions: Sequence[CoverageException],
) -> ProjectCell:
    """Clusters and VMs as one weighted cell; each side kept visible in the note."""
    covered = in_scope = excepted = 0
    parts: list[str] = []
    for metric_key in RUNTIME_BLEND_METRICS:
        spec = get_metric(metric_key)
        items = _select(snapshot.items, item_type=spec.item_type, project=project)
        ratio, _ = _ratio(
            items, signal=spec.signal, metric_key=spec.key, exceptions=exceptions
        )
        covered += ratio.covered
        in_scope += ratio.in_scope
        excepted += ratio.excepted
        if ratio.in_scope:
            unit = _UNIT_BY_ITEM_TYPE.get(spec.item_type, "items")
            parts.append(f"{unit} {ratio.covered} / {ratio.in_scope}")

    blended = Ratio(covered=covered, in_scope=in_scope, excepted=excepted)
    unavailable = tuple(
        sorted(
            (
                _project_required_sources("runtime_k8s", project, config)
                | _project_required_sources("runtime_vm", project, config)
            ).intersection(snapshot.degraded_sources)
        )
    )
    return ProjectCell(
        metric=RUNTIME_COLUMN_KEY,
        label=column_label,
        ratio=blended,
        rag=RAG_NA if unavailable else rag_for(blended.pct, config),
        note=(
            f"incomplete: {', '.join(unavailable)}"
            if unavailable
            else (" · ".join(parts) if parts else "no running prod workloads")
        ),
        unavailable_sources=unavailable,
    )


def _unmapped(snapshot: CoverageSnapshot, config: CoverageConfig) -> UnmappedCounts:
    repos = _select(snapshot.items, item_type=ITEM_REPO)
    accounts = (
        _select(snapshot.items, item_type=ITEM_CLOUD_ACCOUNT)
        if config.collects_cloud()
        else []
    )
    return UnmappedCounts(
        repos=sum(1 for r in repos if not r.projects),
        cloud_accounts=sum(1 for a in accounts if not a.projects),
    )


def build_report(
    snapshot: CoverageSnapshot,
    config: CoverageConfig,
    *,
    now: datetime | None = None,
) -> CoverageReport:
    now = now or datetime.now(UTC)
    today = now.date()
    exceptions = config.active_exceptions(today)

    enabled = set(config.enabled_layers)
    layers = tuple(
        LayerResult(
            key=layer.key,
            label=layer.label,
            scope=layer.scope,
            metrics=tuple(
                _metric_result(snapshot, spec, config, exceptions, today=today)
                for spec in layer.metrics
            ),
        )
        for layer in LAYERS
        if layer.key in enabled
    )

    columns = project_columns_for(config.enabled_layers)
    projects = tuple(
        ProjectRow(
            key=project.key,
            label=project.label,
            flagship=project.flagship,
            cells=tuple(
                _project_cell(
                    snapshot,
                    column_key=column_key,
                    column_label=column_label,
                    project=project.key,
                    config=config,
                    exceptions=exceptions,
                )
                for column_key, column_label in columns
            ),
        )
        for project in config.projects
    )

    age = now - snapshot.as_of
    return CoverageReport(
        as_of=snapshot.as_of,
        collection_mode=snapshot.collection_mode,
        stale=age > timedelta(hours=config.staleness_hours),
        green_pct=config.green_pct,
        amber_pct=config.amber_pct,
        layers=layers,
        projects=projects,
        unmapped=_unmapped(snapshot, config),
        degraded_sources=snapshot.degraded_sources,
    )
