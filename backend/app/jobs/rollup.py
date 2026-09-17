"""Nightly daily_metrics rollup.

Usage:
    python -m app.jobs.rollup                  # yesterday (default)
    python -m app.jobs.rollup --date 2026-05-18 # single day
    python -m app.jobs.rollup --backfill-days 30
"""

from __future__ import annotations

import argparse
import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.api.sla import is_breached, sla_started_at
from app.core.db import session_scope
from app.core.enums import EventType, Severity, Status
from app.core.models import DailyMetric, Finding, FindingEvent
from app.core.policy import get_policy_cache

log = logging.getLogger("secdb.rollup")

_CLOSING = (EventType.fixed, EventType.auto_closed, EventType.suppressed)
_FIXED_TYPES = _CLOSING


@dataclass(frozen=True)
class RollupBucket:
    team: str
    source: str
    severity: Severity
    open_count: int = 0
    new_count: int = 0
    fixed_count: int = 0
    sla_breached_count: int = 0
    median_age_days: float = 0.0


def _end_of_day(target: date) -> datetime:
    return datetime.combine(target, datetime.max.time().replace(microsecond=0), tzinfo=UTC)


def _load_findings(session: Session) -> list[dict[str, Any]]:
    rows = session.execute(
        select(
            Finding.id,
            Finding.owner_team,
            Finding.source,
            Finding.severity,
            Finding.status,
            Finding.reopened_at,
            Finding.upstream_created_at,
            Finding.first_seen_at,
        )
    ).all()
    return [
        {
            "id": r[0],
            "team": r[1],
            "source": r[2],
            "severity": r[3],
            "status": r[4],
            "reopened_at": r[5],
            "upstream_created_at": r[6],
            "first_seen_at": r[7],
        }
        for r in rows
    ]


def _load_events(session: Session) -> dict[UUID, list[tuple[datetime, EventType]]]:
    rows = session.execute(
        select(FindingEvent.finding_id, FindingEvent.occurred_at, FindingEvent.event_type)
        .where(
            FindingEvent.event_type.in_(
                (*_CLOSING, EventType.reopened, EventType.discovered)
            )
        )
        .order_by(FindingEvent.occurred_at)
    ).all()
    out: dict[UUID, list[tuple[datetime, EventType]]] = defaultdict(list)
    for fid, occurred_at, event_type in rows:
        out[fid].append((occurred_at, event_type))
    return out


def _open_state_and_anchor_at(
    finding: dict[str, Any],
    events: list[tuple[datetime, EventType]],
    asof: datetime,
) -> tuple[bool, datetime | None]:
    """Return `(is_open, sla_anchor)` at `asof` using the SLA anchor as the
    start-of-open clock.

    A finding is considered open on `asof` iff its SLA anchor
    (`coalesce(upstream_created_at, first_seen_at)`) precedes `asof` and no
    closing event has occurred at or before `asof` without a later reopen.
    This mirrors `_SLA_ANCHOR` used by `/metrics/summary` so the trend chart
    answers the same "what was open?" question as the KPI strip.

    Notes:
      - `finding.reopened_at` is not used here. Historically it never was
        (would have erased earlier open windows after any later reopen — the
        rollup needs a per-asof snapshot, not the latest wall-clock value).
        With the 2026-05-21 anchor change in `app/api/sla.py`, live age and
        rollup age now share the same definition: `coalesce(upstream_created_at,
        first_seen_at)`. Reopen anchoring (for historical replay) is driven
        from the event log a few lines down.
      - Sources without `upstream_created_at` fall back to `first_seen_at`,
        so trend bars only retreat to the day the dashboard first observed
        them — same as the pre-amendment behaviour for that case.
    """
    anchor = sla_started_at(
        upstream_created_at=finding["upstream_created_at"],
        first_seen_at=finding["first_seen_at"],
    )
    if anchor is None or anchor > asof:
        return False, None

    last_transition: tuple[datetime, EventType] | None = None
    for t, event_type in events:
        if t > asof:
            break
        if event_type in _CLOSING or event_type in (EventType.reopened, EventType.discovered):
            last_transition = (t, event_type)

    if last_transition is not None:
        transition_at, transition_type = last_transition
        if transition_type in _CLOSING:
            return False, None
        if transition_type == EventType.reopened:
            return True, transition_at

    return True, anchor


def compute_rollup(session: Session, target: date) -> list[RollupBucket]:
    asof = _end_of_day(target)
    sla = get_policy_cache().get_sla()
    findings = _load_findings(session)
    events_by_finding = _load_events(session)

    day_start = datetime.combine(target, datetime.min.time(), tzinfo=UTC)
    day_end = asof

    new_counts: dict[tuple[str, str, Severity], int] = defaultdict(int)
    fixed_counts: dict[tuple[str, str, Severity], int] = defaultdict(int)

    #: `new_count` anchors on the SLA-anchor
    # (`coalesce(upstream_created_at, first_seen_at)`) rather than the
    # `discovered` event timestamp, to stay consistent with `open_count` and
    # with `_SLA_ANCHOR`. A Dependabot alert from 2024-08-15 ingested today
    # therefore counts as "new" on 2024-08-15, not today.
    new_anchor = func.coalesce(Finding.upstream_created_at, Finding.first_seen_at)
    new_rows = session.execute(
        select(Finding.owner_team, Finding.source, Finding.severity, func.count())
        .where(
            new_anchor >= day_start,
            new_anchor <= day_end,
        )
        .group_by(Finding.owner_team, Finding.source, Finding.severity)
    ).all()
    for team, source, severity, cnt in new_rows:
        new_counts[(team, source, severity)] = int(cnt)

    fixed_rows = session.execute(
        select(Finding.owner_team, Finding.source, Finding.severity, func.count())
        .select_from(FindingEvent)
        .join(Finding, Finding.id == FindingEvent.finding_id)
        .where(
            FindingEvent.event_type.in_(_FIXED_TYPES),
            FindingEvent.occurred_at >= day_start,
            FindingEvent.occurred_at <= day_end,
        )
        .group_by(Finding.owner_team, Finding.source, Finding.severity)
    ).all()
    for team, source, severity, cnt in fixed_rows:
        fixed_counts[(team, source, severity)] = int(cnt)

    open_ages: dict[tuple[str, str, Severity], list[float]] = defaultdict(list)
    open_counts: dict[tuple[str, str, Severity], int] = defaultdict(int)
    breach_counts: dict[tuple[str, str, Severity], int] = defaultdict(int)

    for f in findings:
        key = (f["team"], f["source"], f["severity"])
        evs = events_by_finding.get(f["id"], [])
        is_open, anchor = _open_state_and_anchor_at(f, evs, asof)
        if not is_open or anchor is None:
            continue
        open_counts[key] += 1
        age_days = (asof - anchor).total_seconds() / 86_400
        open_ages[key].append(age_days)
        if is_breached(sla, f["severity"], Status.open, anchor, now=asof):
            breach_counts[key] += 1

    all_keys = set(open_counts) | set(new_counts) | set(fixed_counts)
    buckets: list[RollupBucket] = []
    for key in sorted(all_keys):
        team, source, severity = key
        ages = open_ages.get(key, [])
        median = statistics.median(ages) if ages else 0.0
        buckets.append(
            RollupBucket(
                team=team,
                source=source,
                severity=severity,
                open_count=open_counts.get(key, 0),
                new_count=new_counts.get(key, 0),
                fixed_count=fixed_counts.get(key, 0),
                sla_breached_count=breach_counts.get(key, 0),
                median_age_days=float(median),
            )
        )
    return buckets


def upsert_rollup(session: Session, target: date, buckets: list[RollupBucket]) -> int:
    if not buckets:
        return 0
    rows = [
        {
            "date": target,
            "team": b.team,
            "source": b.source,
            "severity": b.severity,
            "open_count": b.open_count,
            "new_count": b.new_count,
            "fixed_count": b.fixed_count,
            "sla_breached_count": b.sla_breached_count,
            "median_age_days": b.median_age_days,
        }
        for b in buckets
    ]
    stmt = insert(DailyMetric).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_daily_metrics_date_team_source_sev",
        set_={
            "open_count": stmt.excluded.open_count,
            "new_count": stmt.excluded.new_count,
            "fixed_count": stmt.excluded.fixed_count,
            "sla_breached_count": stmt.excluded.sla_breached_count,
            "median_age_days": stmt.excluded.median_age_days,
        },
    )
    session.execute(stmt)
    return len(rows)


def rollup_date(session: Session, target: date) -> int:
    buckets = compute_rollup(session, target)
    n = upsert_rollup(session, target, buckets)
    log.info("rollup.done date=%s buckets=%d", target.isoformat(), n)
    return n


def print_status(session: Session) -> None:
    """Print Cloud SQL / local DB health for trend charts (operator diagnostics)."""
    from sqlalchemy import text

    findings = session.execute(
        text(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE owner_team = 'unowned') AS unowned "
            "FROM findings"
        )
    ).one()
    metrics = session.execute(
        text(
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(open_count), 0) AS open_sum, "
            "MIN(date) AS min_date, MAX(date) AS max_date "
            "FROM daily_metrics"
        )
    ).one()
    dev_open = session.execute(
        text(
            "SELECT COALESCE(SUM(open_count), 0) "
            "FROM daily_metrics "
            "WHERE team != 'unowned' AND open_count > 0 "
            "AND date >= CURRENT_DATE - 30"
        )
    ).scalar_one()
    print(
        f"findings total={findings.total} unowned={findings.unowned} "
        f"daily_metrics rows={metrics.rows} open_sum={metrics.open_sum} "
        f"date_range={metrics.min_date}..{metrics.max_date} "
        f"dev_view_open_30d={dev_open}"
    )
    if int(metrics.rows or 0) == 0:
        print(
            "hint: run rollup on THIS database — "
            "local: make rollup-backfill (LOCAL_DATABASE_URL); "
            "GCP: make cloud-rollup-backfill or make rollup-backfill-gcp (GCP_DATABASE_URL)"
        )
    elif int(dev_open or 0) == 0 and int(findings.unowned or 0) > 0:
        print(
            "hint: findings are mostly unowned — trend charts filter to dev-view teams. "
            "Re-run GCP pollers after ownership.yaml is in the config bucket, then re-run rollup."
        )


def backfill_days(session: Session, days: int) -> int:
    """Roll up each of the last N calendar days ending yesterday."""
    if days < 1:
        raise ValueError("days must be >= 1")
    yesterday = date.today() - timedelta(days=1)
    dates = [yesterday - timedelta(days=i) for i in range(days - 1, -1, -1)]
    total = 0
    for d in dates:
        total += rollup_date(session, d)
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Roll up daily_metrics")
    parser.add_argument("--date", type=date.fromisoformat, help="Single day (YYYY-MM-DD)")
    parser.add_argument(
        "--backfill-days",
        type=int,
        metavar="N",
        help="Roll up each of the last N calendar days ending yesterday",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print findings/daily_metrics counts and exit (no rollup)",
    )
    args = parser.parse_args()

    if args.status:
        with session_scope() as session:
            print_status(session)
        return

    from app.core.config_store import get_config_cache
    from app.internal.ownership_reresolve import core_reresolve

    with session_scope() as session:
        ownership = get_config_cache().get_ownership()
        rr = core_reresolve(session, ownership, actor="system:rollup")
    prestep_updated = rr.updated
    if prestep_updated > 0:
        log.info("rollup.prestep_reresolve updated=%d", prestep_updated)

    if args.backfill_days is not None:
        if args.backfill_days < 1:
            raise SystemExit("--backfill-days must be >= 1")
        with session_scope() as session:
            total = backfill_days(session, args.backfill_days)
        log.info("rollup.complete days=%d rows=%d", args.backfill_days, total)
        return

    if args.date is not None:
        dates = [args.date]
    elif prestep_updated > 0:
        with session_scope() as session:
            total = backfill_days(session, 30)
        log.info("rollup.complete days=30 rows=%d (after ownership pre-step)", total)
        return
    else:
        dates = [date.today() - timedelta(days=1)]

    total = 0
    with session_scope() as session:
        for d in dates:
            total += rollup_date(session, d)
    log.info("rollup.complete days=%d rows=%d", len(dates), total)


if __name__ == "__main__":
    main()
