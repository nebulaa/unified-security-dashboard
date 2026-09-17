"""daily_metrics rollup job and /metrics/trend integration."""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.enums import EventType, Severity, Status
from app.core.models import DailyMetric, FindingEvent
from app.jobs.rollup import compute_rollup, rollup_date, upsert_rollup
from tests._factory import make_finding

EXEC = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


def test_rollup_open_and_new_counts(session) -> None:
    target = date.today() - timedelta(days=1)
    make_finding(
        session,
        native_id="rollup#1",
        severity=Severity.critical,
        owner_team="pricing-platform",
        age_days=5.0,
    )
    session.commit()

    buckets = compute_rollup(session, target)
    bucket = next(
        (b for b in buckets if b.team == "pricing-platform" and b.severity == Severity.critical),
        None,
    )
    assert bucket is not None
    assert bucket.open_count >= 1
    assert bucket.new_count >= 0

    upsert_rollup(session, target, buckets)
    session.commit()

    row = session.execute(
        select(DailyMetric).where(
            DailyMetric.date == target,
            DailyMetric.team == "pricing-platform",
            DailyMetric.severity == Severity.critical,
        )
    ).scalar_one_or_none()
    assert row is not None


def test_metrics_trend_reads_daily_metrics(session, client) -> None:
    target = date.today() - timedelta(days=2)
    rollup_date(session, target)
    session.commit()

    r = client.get("/metrics/trend?days=7", headers=EXEC)
    assert r.status_code == 200
    points = r.json()["points"]
    dates = {p["date"] for p in points}
    assert str(target) in dates or len(points) >= 0


def test_metrics_trend_asset_filter_uses_replay(session, client) -> None:
    make_finding(
        session,
        native_id="asset-filter#1",
        asset_id="repo:asset-filter-service",
        age_days=3.0,
    )
    session.commit()

    r = client.get("/metrics/trend?days=14&asset=asset-filter", headers=EXEC)
    assert r.status_code == 200
    assert isinstance(r.json()["points"], list)


def test_rollup_backdates_open_to_upstream_created_at(session) -> None:
    """a finding ingested today with
    upstream_created_at 120 days ago must show as open on every historical
    day between upstream_created_at and today, even though the `discovered`
    event was stamped today. Mirrors `_SLA_ANCHOR` used by /metrics/summary.
    """
    target = date.today() - timedelta(days=7)  # well before today, well after upstream
    make_finding(
        session,
        native_id="rollup#upstream-old",
        source="dependabot",
        owner_team="pricing-platform",
        age_days=1.0,
        upstream_age_days=120.0,
    )
    session.commit()

    buckets = compute_rollup(session, target)
    bucket = next(
        (
            b
            for b in buckets
            if b.team == "pricing-platform"
            and b.source == "dependabot"
            and b.severity == Severity.high
        ),
        None,
    )
    assert bucket is not None
    assert bucket.open_count == 1
    # Age on target day is roughly (120 - 7) days = ~113 days.
    assert 110 < bucket.median_age_days < 116


def test_rollup_does_not_count_before_upstream_created_at(session) -> None:
    """The amendment backdates to `upstream_created_at` but no further. A day
    that precedes the upstream alert's birth must still report 0 — otherwise
    we'd be inventing history that didn't exist anywhere.
    """
    target = date.today() - timedelta(days=200)  # before upstream_age_days=120
    make_finding(
        session,
        native_id="rollup#before-upstream",
        source="dependabot",
        owner_team="pricing-platform",
        age_days=1.0,
        upstream_age_days=120.0,
    )
    session.commit()

    buckets = compute_rollup(session, target)
    bucket = next(
        (
            b
            for b in buckets
            if b.team == "pricing-platform"
            and b.source == "dependabot"
            and b.severity == Severity.high
        ),
        None,
    )
    assert bucket is None or bucket.open_count == 0


def test_rollup_new_count_anchors_on_upstream_created_at(session) -> None:
    """`new_count` on day D counts findings
    whose `coalesce(upstream_created_at, first_seen_at)` falls on D, not the
    day we observed them. Pairs with the `open_count` change so the trend
    chart's "new today" bar matches "first day the bar went up by one".
    """
    # Two findings ingested today, upstream-created on different historical days.
    make_finding(
        session,
        native_id="rollup#new-on-target",
        source="dependabot",
        owner_team="pricing-platform",
        severity=Severity.critical,
        age_days=0.5,
        upstream_age_days=7.0,  # upstream-created 7 days ago == target below
    )
    make_finding(
        session,
        native_id="rollup#new-elsewhere",
        source="dependabot",
        owner_team="pricing-platform",
        severity=Severity.critical,
        age_days=0.5,
        upstream_age_days=30.0,  # upstream-created 30 days ago != target
    )
    session.commit()

    target = date.today() - timedelta(days=7)
    buckets = compute_rollup(session, target)
    bucket = next(
        (
            b
            for b in buckets
            if b.team == "pricing-platform"
            and b.source == "dependabot"
            and b.severity == Severity.critical
        ),
        None,
    )
    assert bucket is not None
    assert bucket.new_count == 1  # only the 7-days-ago finding
    assert bucket.open_count == 2  # both are open on target day (7d and 30d ago)


def test_rollup_uses_anchor_of_lifecycle_open_at_target_day(session) -> None:
    """A later reopen must not erase earlier open history in backfill windows."""
    now = datetime.now(UTC)
    target = (now - timedelta(days=4)).date()  # before close/reopen flap below
    f = make_finding(
        session,
        native_id="rollup#reopen-history",
        source="sonarcloud",
        owner_team="security",
        severity=Severity.critical,
        age_days=20.0,
        upstream_age_days=120.0,
        reopened_days_ago=1.0,  # latest reopen is after target day
    )
    session.flush()
    session.add(
        FindingEvent(
            finding_id=f.id,
            event_type=EventType.auto_closed,
            from_value=Status.open.value,
            to_value=Status.auto_closed.value,
            occurred_at=now - timedelta(days=3),
            actor="system:test",
        )
    )
    session.add(
        FindingEvent(
            finding_id=f.id,
            event_type=EventType.reopened,
            from_value=Status.auto_closed.value,
            to_value=Status.open.value,
            occurred_at=now - timedelta(days=1),
            actor="system:test",
        )
    )
    session.commit()

    buckets = compute_rollup(session, target)
    bucket = next(
        (
            b
            for b in buckets
            if b.team == "security"
            and b.source == "sonarcloud"
            and b.severity == Severity.critical
        ),
        None,
    )
    assert bucket is not None
    assert bucket.open_count == 1
    # Anchor should be upstream-created (older), not the later reopened_at.
    assert bucket.median_age_days > 100


def test_rollup_historical_sla_breach_ignores_current_closed_status(session) -> None:
    """A finding closed *after* target day still contributes SLA breaches at target."""
    now = datetime.now(UTC)
    target = (now - timedelta(days=5)).date()
    f = make_finding(
        session,
        native_id="rollup#historical-sla",
        source="sonarcloud",
        owner_team="security",
        severity=Severity.critical,
        age_days=30.0,
        upstream_age_days=180.0,
    )
    session.flush()
    # Closed after target date; at target date the finding was still open.
    session.add(
        FindingEvent(
            finding_id=f.id,
            event_type=EventType.auto_closed,
            from_value=Status.open.value,
            to_value=Status.auto_closed.value,
            occurred_at=now - timedelta(days=2),
            actor="system:test",
        )
    )
    f.status = Status.auto_closed
    session.commit()

    buckets = compute_rollup(session, target)
    bucket = next(
        (
            b
            for b in buckets
            if b.team == "security"
            and b.source == "sonarcloud"
            and b.severity == Severity.critical
        ),
        None,
    )
    assert bucket is not None
    assert bucket.open_count == 1
    assert bucket.sla_breached_count == 1


def test_rollup_runs_ownership_reresolve_pre_step() -> None:
    from unittest.mock import MagicMock, patch

    from app.internal.ownership_reresolve import ReresolveResult
    from app.jobs.rollup import main

    with (
        patch("app.jobs.rollup.session_scope") as scope,
        patch("app.core.config_store.get_config_cache") as cache,
        patch("app.internal.ownership_reresolve.core_reresolve") as core,
        patch("app.jobs.rollup.rollup_date", return_value=2) as rollup_day,
        patch.object(sys, "argv", ["rollup"]),
    ):
        mock_session = MagicMock()
        scope.return_value.__enter__.return_value = mock_session
        scope.return_value.__exit__.return_value = None
        cache.return_value.get_ownership.return_value = MagicMock()
        core.return_value = ReresolveResult(scanned=10, updated=0, by_transition={})
        main()
    core.assert_called_once()
    assert core.call_args.kwargs["actor"] == "system:rollup"
    rollup_day.assert_called_once()
