"""Coverage snapshot types — the collector's output and the computed report.

A snapshot is a flat list of inventory items. Each item carries its own Y
membership (`in_scope`), the key projects that claim it, and the set of signals
a collector observed. Keeping items flat means a new metric is a new signal on
an existing item, not a new table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class InventoryItem:
    item_type: str
    item_id: str
    display: str
    # Production (cloud items) or eligible (repos). Out-of-scope items stay in
    # the snapshot so secondaries like "all environments" can still divide by them.
    in_scope: bool
    projects: tuple[str, ...] = ()
    signals: frozenset[str] = frozenset()

    def has(self, signal: str) -> bool:
        return signal in self.signals


@dataclass(frozen=True)
class HistoryPoint:
    """One past day's percentage per metric key — drives sparkline and delta."""

    day: date
    pct: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageSnapshot:
    as_of: datetime
    items: tuple[InventoryItem, ...] = ()
    history: tuple[HistoryPoint, ...] = ()
    collection_mode: str = "live"
    # Collectors that failed on this run. Their metrics keep the previous
    # snapshot's numbers rather than reporting a full denominator with no X.
    degraded_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Ratio:
    covered: int
    in_scope: int
    excepted: int = 0

    @property
    def pct(self) -> float | None:
        if self.in_scope == 0:
            return None
        return round(self.covered / self.in_scope * 100, 1)

    @property
    def gaps(self) -> int:
        return max(self.in_scope - self.covered, 0)


@dataclass(frozen=True)
class SecondaryResult:
    key: str
    label: str
    ratio: Ratio
    unit: str


@dataclass(frozen=True)
class MetricResult:
    key: str
    label: str
    definition: str
    unit: str
    ratio: Ratio
    rag: str
    delta_pts: float | None
    trend: tuple[float, ...]
    gap_items: tuple[str, ...]
    unavailable_sources: tuple[str, ...] = ()
    secondary: SecondaryResult | None = None


@dataclass(frozen=True)
class LayerResult:
    key: str
    label: str
    scope: str
    metrics: tuple[MetricResult, ...]


@dataclass(frozen=True)
class ProjectCell:
    metric: str
    label: str
    ratio: Ratio
    rag: str
    note: str
    unavailable_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectRow:
    key: str
    label: str
    flagship: bool
    cells: tuple[ProjectCell, ...]


@dataclass(frozen=True)
class UnmappedCounts:
    repos: int
    cloud_accounts: int


@dataclass(frozen=True)
class CoverageReport:
    as_of: datetime
    collection_mode: str
    stale: bool
    green_pct: float
    amber_pct: float
    layers: tuple[LayerResult, ...]
    projects: tuple[ProjectRow, ...]
    unmapped: UnmappedCounts
    degraded_sources: tuple[str, ...] = ()
