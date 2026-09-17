"""Re-stamp Finding.owner_team from ownership.yaml and emit audit events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.config_store import OwnershipMap, get_config_cache
from app.core.db import session_scope
from app.core.enums import EventType
from app.core.finding_owner import resolve_finding_owner_team
from app.core.models import Finding, FindingEvent

log = logging.getLogger("secdb.ownership_reresolve")

_TRANSITION_SAMPLE_LIMIT = 20


@dataclass
class OwnershipTransition:
    finding_id: UUID
    asset_id: str
    from_team: str
    to_team: str


@dataclass
class ReresolveResult:
    scanned: int = 0
    updated: int = 0
    transitions_sample: list[OwnershipTransition] = field(default_factory=list)
    by_transition: dict[str, int] = field(default_factory=dict)

    def record_transition(self, finding_id: UUID, asset_id: str, from_team: str, to_team: str) -> None:
        key = f"{from_team} -> {to_team}"
        self.by_transition[key] = self.by_transition.get(key, 0) + 1
        if len(self.transitions_sample) < _TRANSITION_SAMPLE_LIMIT:
            self.transitions_sample.append(
                OwnershipTransition(
                    finding_id=finding_id,
                    asset_id=asset_id,
                    from_team=from_team,
                    to_team=to_team,
                )
            )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _emit_ownership_changed(
    session: Session,
    finding_id: UUID,
    from_team: str,
    to_team: str,
    actor: str,
) -> None:
    session.add(
        FindingEvent(
            finding_id=finding_id,
            event_type=EventType.ownership_changed,
            from_value=from_team,
            to_value=to_team,
            actor=actor,
            occurred_at=_utcnow(),
        )
    )


def core_reresolve(
    session: Session,
    ownership: OwnershipMap,
    actor: str,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
    wiz_service_to_team: dict[str, str] | None = None,
) -> ReresolveResult:
    """Walk all findings; update owner_team when resolved ownership disagrees.

    Wiz `wizservice:*` and `cloudres:*` rows use registry + platform_pillar tags
    (not ownership.yaml) — see `resolve_finding_owner_team`.
    """
    if wiz_service_to_team is None:
        wiz_service_to_team = get_config_cache().get_component_registry().wiz_service_to_team

    result = ReresolveResult()
    last_id: UUID | None = None

    while True:
        q = (
            select(
                Finding.id,
                Finding.source,
                Finding.asset_id,
                Finding.owner_team,
                Finding.tags,
            )
            .order_by(Finding.id)
            .limit(batch_size)
        )
        if last_id is not None:
            q = q.where(Finding.id > last_id)
        rows = session.execute(q).all()
        if not rows:
            break

        for finding_id, source, asset_id, owner_team, tags in rows:
            result.scanned += 1
            resolved = resolve_finding_owner_team(
                source=source,
                asset_id=asset_id,
                tags=list(tags or []),
                ownership=ownership,
                wiz_service_to_team=wiz_service_to_team,
            )
            if resolved == owner_team:
                continue

            result.updated += 1
            result.record_transition(finding_id, asset_id, owner_team, resolved)

            if dry_run:
                continue

            finding = session.get(Finding, finding_id)
            if finding is None:
                continue
            _emit_ownership_changed(session, finding_id, owner_team, resolved, actor)
            finding.owner_team = resolved

        last_id = rows[-1][0]

    log.info(
        "ownership_reresolve.done actor=%s scanned=%d updated=%d dry_run=%s",
        actor,
        result.scanned,
        result.updated,
        dry_run,
    )
    return result


def _uses_cloud_run() -> bool:
    settings = get_settings()
    return bool(settings.ingest_transport == "pubsub" and settings.gcp_region and settings.pubsub_project)


def maybe_trigger_rollup_backfill(updated: int, *, async_mode: bool) -> bool:
    """When rows changed, refresh daily_metrics (30d). Async on API config push."""
    if updated < 1:
        return False

    settings = get_settings()
    if async_mode and _uses_cloud_run():
        from app.internal.cloud_run_jobs import run_cloud_run_job

        execution = run_cloud_run_job(
            project=settings.pubsub_project or "",
            region=settings.gcp_region or "",
            job_name=settings.rollup_job,
            args=["-m", "app.jobs.rollup", "--backfill-days", "30"],
        )
        log.info("ownership_reresolve.rollup_triggered execution=%s", execution)
        return True

    from app.jobs.rollup import backfill_days

    with session_scope() as session:
        rows = backfill_days(session, 30)
    log.info("ownership_reresolve.rollup_backfill_inline rows=%d", rows)
    return True


def print_status(session: Session) -> None:
    """Operator diagnostics: team distribution + recent ownership_changed events."""
    dist_rows = session.execute(
        select(Finding.owner_team, func.count())
        .group_by(Finding.owner_team)
        .order_by(func.count().desc())
    ).all()
    since = _utcnow() - timedelta(days=7)
    recent_count = session.execute(
        select(func.count())
        .select_from(FindingEvent)
        .where(
            FindingEvent.event_type == EventType.ownership_changed,
            FindingEvent.occurred_at >= since,
        )
    ).scalar_one()

    print("owner_team distribution:")
    for team, cnt in dist_rows[:30]:
        print(f"  {team}: {cnt}")
    if len(dist_rows) > 30:
        print(f"  ... and {len(dist_rows) - 30} more teams")

    unowned = next((c for t, c in dist_rows if t == "unowned"), 0)
    excluded = next((c for t, c in dist_rows if t == "excluded"), 0)
    print(f"unowned={unowned} excluded={excluded}")
    print(f"ownership_changed events (last 7d): {recent_count}")

    recent = session.execute(
        select(
            FindingEvent.occurred_at,
            FindingEvent.from_value,
            FindingEvent.to_value,
            FindingEvent.actor,
        )
        .where(FindingEvent.event_type == EventType.ownership_changed)
        .order_by(FindingEvent.occurred_at.desc())
        .limit(50)
    ).all()
    if recent:
        print("recent ownership_changed (up to 50):")
        for occurred_at, from_v, to_v, actor in recent:
            print(f"  {occurred_at.isoformat()} {from_v} -> {to_v} ({actor})")


def reresolve_result_to_dict(result: ReresolveResult) -> dict[str, Any]:
    return {
        "scanned": result.scanned,
        "updated": result.updated,
        "by_transition": dict(result.by_transition),
        "transitions_sample": [
            {
                "finding_id": str(t.finding_id),
                "asset_id": t.asset_id,
                "from_team": t.from_team,
                "to_team": t.to_team,
            }
            for t in result.transitions_sample
        ],
    }
