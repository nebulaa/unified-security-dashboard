"""Coverage collector.

    python -m app.coverage.collect --sample     # local prototype data, no credentials
    python -m app.coverage.collect              # live GitHub + Sonar collection
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta

from app.coverage.compute import TREND_WINDOW_DAYS, build_report
from app.coverage.config import CoverageConfig, get_coverage_config
from app.coverage.model import CoverageSnapshot, HistoryPoint, InventoryItem
from app.coverage.spec import ITEM_REPO
from app.coverage.store import write

log = logging.getLogger("secdb.coverage.collect")

PRODUCT = "product-offer-order"

# Month-on-month movement baked into the sample history, so the tiles show a
# plausible direction of travel rather than a flat line.
_SAMPLE_DELTAS: dict[str, float] = {
    "sonar": 3.0,
    "dependabot": 1.0,
}

# Sample repos matching the exception entries in `config/coverage.yaml`.
_SAMPLE_EXCEPTED_REPOS = (
    "sample-legacy-exporter",
    "sample-vendor-fork-tools",
    "sample-docs-site",
    "sample-terraform-sandbox",
    "sample-data-notebooks",
    "sample-archived-bridge",
)


def _item(
    item_type: str,
    item_id: str,
    display: str,
    *,
    in_scope: bool,
    projects: tuple[str, ...] = (),
    signals: tuple[str, ...] = (),
) -> InventoryItem:
    return InventoryItem(
        item_type=item_type,
        item_id=item_id,
        display=display,
        in_scope=in_scope,
        projects=projects,
        signals=frozenset(signals),
    )


def _sample_repos() -> list[InventoryItem]:
    """239 eligible repos: 42 Product (the PRODUCT code slice), 6 carrying an exception."""
    items: list[InventoryItem] = []

    for i in range(1, 43):
        name = f"product-service-{i:02d}"
        signals = ["dependabot_enabled"]
        if i <= 37:
            signals.append("sonar_analyzed_30d")
        if i <= 26:
            signals.append("dependabot_version_updates")
        items.append(
            _item(
                ITEM_REPO,
                f"repo:ExampleOrg/{name}",
                name,
                in_scope=True,
                projects=(PRODUCT,),
                signals=tuple(signals),
            )
        )

    for i in range(1, 192):
        name = f"exampleorg-service-{i:03d}"
        signals = []
        if i <= 175:
            signals.append("sonar_analyzed_30d")
        if i <= 182:
            signals.append("dependabot_enabled")
        if i <= 116:
            signals.append("dependabot_version_updates")
        items.append(
            _item(
                ITEM_REPO,
                f"repo:ExampleOrg/{name}",
                name,
                in_scope=True,
                signals=tuple(signals),
            )
        )

    # Excepted repos are in scope and uncovered — they must leave the denominator
    # through the exception, not by being quietly dropped from inventory.
    items += [
        _item(ITEM_REPO, f"repo:ExampleOrg/{name}", name, in_scope=True)
        for name in _SAMPLE_EXCEPTED_REPOS
    ]

    # Archived / forked / dormant repos stay in the snapshot but out of Y.
    items += [
        _item(
            ITEM_REPO,
            f"repo:ExampleOrg/exampleorg-dormant-{i:03d}",
            f"exampleorg-dormant-{i:03d}",
            in_scope=False,
        )
        for i in range(1, 62)
    ]

    return items


def _sample_history(
    items: list[InventoryItem], *, now: datetime, config: CoverageConfig
) -> tuple[HistoryPoint, ...]:
    """Synthesize 90 days ending on today's real figures.

    Each series is linear, so the point `DELTA_WINDOW_DAYS` back reproduces the
    configured month-on-month movement exactly.
    """
    today = build_report(CoverageSnapshot(as_of=now, items=tuple(items)), config, now=now)
    current = {
        metric.key: metric.ratio.pct
        for layer in today.layers
        for metric in layer.metrics
        if metric.ratio.pct is not None
    }

    points: list[HistoryPoint] = []
    for offset in range(TREND_WINDOW_DAYS, -1, -1):
        day = (now - timedelta(days=offset)).date()
        pct: dict[str, float] = {}
        for key, value in current.items():
            delta = _SAMPLE_DELTAS.get(key, 0.0)
            # 3 delta-windows of history, so t-30d lands exactly one delta below.
            drop = delta * (offset / 30)
            pct[key] = round(min(100.0, max(0.0, value - drop)), 1)
        points.append(HistoryPoint(day=day, pct=pct))
    return tuple(points)


def build_sample_snapshot(
    now: datetime | None = None, config: CoverageConfig | None = None
) -> CoverageSnapshot:
    now = now or datetime.now(UTC)
    config = config or get_coverage_config()
    items = _sample_repos()
    return CoverageSnapshot(
        as_of=now,
        items=tuple(items),
        history=_sample_history(items, now=now, config=config),
        collection_mode="sample",
    )


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a cloud security coverage snapshot")
    parser.add_argument(
        "--sample",
        action="store_true",
        help="write prototype repo data instead of calling GitHub and Sonar",
    )
    args = parser.parse_args(argv)

    if args.sample:
        snapshot = build_sample_snapshot()
    else:
        from app.core.config import get_settings
        from app.coverage.live import collect_live

        snapshot = collect_live(get_settings(), get_coverage_config())

    path = write(snapshot)
    log.info(
        "coverage.snapshot_written mode=%s items=%d degraded=%s path=%s",
        snapshot.collection_mode,
        len(snapshot.items),
        ",".join(snapshot.degraded_sources) or "none",
        path,
    )
    return 0


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(run())


if __name__ == "__main__":
    main()
