"""Tiny finding/event factory for API tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import EventType, Severity, Status
from app.core.models import Finding, FindingEvent


def make_finding(
    session: Session,
    *,
    source: str = "dependabot",
    native_id: str = "ExampleOrg/example-service#1",
    severity: Severity = Severity.high,
    status: Status = Status.open,
    owner_team: str = "pricing-platform",
    asset_id: str | None = None,
    age_days: float = 1.0,
    upstream_age_days: float | None = None,
    reopened_days_ago: float | None = None,
    title: str = "Test finding",
    tags: list[str] | None = None,
) -> Finding:
    """Build a finding for tests.

    `age_days` controls `first_seen_at` (when our system ingested it). Use
    `upstream_age_days` to set `upstream_created_at` independently — this is what
    SLA / age math actually anchors on. `reopened_days_ago`, when set, fakes a
    recent auto_closed -> open transition (used to verify the row carries the
    event-log timestamp without the anchor moving — `reopened_at` is no longer
    part of `sla_started_at`; see `app/api/sla.py`).
    """
    namespace = UUID(get_settings().namespace_secdb)
    fid = uuid5(namespace, f"{source}:{native_id}")
    now = datetime.now(UTC)
    first_seen = now - timedelta(days=age_days)
    upstream = (
        now - timedelta(days=upstream_age_days)
        if upstream_age_days is not None
        else None
    )
    reopened = (
        now - timedelta(days=reopened_days_ago)
        if reopened_days_ago is not None
        else None
    )
    asset = asset_id or f"repo:{native_id.split('#')[0]}"
    f = Finding(
        id=fid,
        source=source,
        native_id=native_id,
        title=title,
        description="",
        severity=severity,
        cve_id="CVE-2024-9999",
        cwe_id="CWE-79",
        asset_id=asset,
        asset_type="github_repo",
        asset_root=asset,
        asset_display=native_id.split("#")[0],
        owner_team=owner_team,
        status=status,
        first_seen_at=first_seen,
        last_seen_at=now,
        upstream_created_at=upstream,
        reopened_at=reopened,
        consecutive_misses=0,
        raw_payload_uri="file:///tmp/test.json",
        tags=list(tags or []),
    )
    session.add(f)
    session.flush()
    session.add(
        FindingEvent(
            finding_id=fid,
            event_type=EventType.discovered,
            from_value=None,
            to_value=Status.open.value,
            occurred_at=first_seen,
            actor=f"system:{source}_ingest",
        )
    )
    if status in (Status.fixed, Status.auto_closed):
        event_type = EventType.fixed if status == Status.fixed else EventType.auto_closed
        session.add(
            FindingEvent(
                finding_id=fid,
                event_type=event_type,
                from_value=Status.open.value,
                to_value=status.value,
                occurred_at=now,
                actor="system:test",
            )
        )
    return f
