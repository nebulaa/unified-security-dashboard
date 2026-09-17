"""Live coverage orchestration — GitHub inventory plus Sonar signals."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from app.adapters.secrets import SecretRef, build_secret_backend
from app.core.config import Settings
from app.core.config_store import get_config_cache
from app.coverage.compute import TREND_WINDOW_DAYS, build_report
from app.coverage.config import CoverageConfig
from app.coverage.connectors.github import GitHubConnector
from app.coverage.connectors.sonar import SonarConnector
from app.coverage.model import CoverageSnapshot, HistoryPoint, InventoryItem
from app.coverage.spec import ITEM_REPO
from app.coverage.store import SnapshotNotFoundError, load_latest

log = logging.getLogger("secdb.coverage.live")


def _add_signal_to_ids(
    items: list[InventoryItem], *, item_type: str, item_ids: set[str], signal: str
) -> list[InventoryItem]:
    lowered = {item_id.lower() for item_id in item_ids}
    return [
        replace(item, signals=item.signals | {signal})
        if item.item_type == item_type and item.item_id.lower() in lowered
        else item
        for item in items
    ]


def _sonar_map() -> dict[str, str]:
    registry = get_config_cache().get_component_registry()
    result: dict[str, str] = {}
    for component in registry.components:
        if not component.repo:
            continue
        for project_key in component.sonar_projects:
            result[project_key] = component.repo
    return result


def _history(
    *,
    now: datetime,
    items: list[InventoryItem],
    config: CoverageConfig,
    degraded: set[str],
) -> tuple[HistoryPoint, ...]:
    previous: tuple[HistoryPoint, ...] = ()
    try:
        existing = load_latest()
        if existing.collection_mode == "live":
            previous = existing.history
    except SnapshotNotFoundError:
        pass

    provisional = CoverageSnapshot(
        as_of=now,
        items=tuple(items),
        degraded_sources=tuple(sorted(degraded)),
        collection_mode="live",
    )
    report = build_report(provisional, config, now=now)
    pct = {
        metric.key: metric.ratio.pct
        for layer in report.layers
        for metric in layer.metrics
        if metric.ratio.pct is not None and not metric.unavailable_sources
    }
    today = HistoryPoint(day=now.date(), pct=pct)
    cutoff = now.date() - timedelta(days=TREND_WINDOW_DAYS)
    old = [point for point in previous if point.day >= cutoff and point.day != now.date()]
    return tuple([*old, today])


def collect_live(
    settings: Settings,
    config: CoverageConfig,
    *,
    now: datetime | None = None,
) -> CoverageSnapshot:
    now = now or datetime.now(UTC)
    degraded: set[str] = set()
    items: list[InventoryItem] = []
    secrets = build_secret_backend(settings)

    github: GitHubConnector | None = None
    try:
        github = GitHubConnector(
            org=settings.github_org,
            # `gh auth token` is the preferred local credential; Cloud Run has
            # no GH_TOKEN and therefore uses the managed Dependabot PAT.
            token=os.environ.get("GH_TOKEN") or secrets.get(SecretRef.dependabot_pat()),
        )
        items.extend(github.collect(config, now=now))
        log.info("coverage source=github items=%d", len(items))
    except Exception:
        degraded.add("github")
        log.exception("coverage source=github failed")
    finally:
        if github:
            github.close()

    sonar: SonarConnector | None = None
    try:
        sonar = SonarConnector(
            token=secrets.get(SecretRef.sonarcloud_token()),
            organizations=tuple(settings.sonar_orgs),
            base_url=settings.sonar_base_url,
        )
        repo_names = {
            item.display for item in items if item.item_type == ITEM_REPO
        }
        covered = sonar.covered_repo_ids(
            org=settings.github_org,
            repo_names=repo_names,
            explicit_map=_sonar_map(),
            now=now,
        )
        items = _add_signal_to_ids(
            items,
            item_type=ITEM_REPO,
            item_ids=covered,
            signal="sonar_analyzed_30d",
        )
        log.info("coverage source=sonar covered_repos=%d", len(covered))
    except Exception:
        degraded.add("sonar")
        log.exception("coverage source=sonar failed")
    finally:
        if sonar:
            sonar.close()

    history = _history(
        now=now, items=items, config=config, degraded=degraded
    )
    return CoverageSnapshot(
        as_of=now,
        items=tuple(items),
        history=history,
        collection_mode="live",
        degraded_sources=tuple(sorted(degraded)),
    )
