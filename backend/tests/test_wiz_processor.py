"""Wiz snapshot processor lifecycle."""

from __future__ import annotations

from uuid import uuid4

from app.core.enums import Severity, Status
from app.core.models import Finding
from app.normalizer.mappers.wiz import WIZ_SOURCE, map_node
from app.normalizer.processor import process_snapshot


def _wiz_finding(wiz_id: str = "abc", category: str = "issue"):
    return map_node(
        {
            "id": wiz_id,
            "severity": "CRITICAL",
            "status": "OPEN",
            "createdAt": "2025-01-01T00:00:00Z",
            "applicationServices": [{"displayName": "unknown-service"}],
        },
        category,
    )


def test_wiz_auto_close_after_threshold(session) -> None:
    poll1 = uuid4()
    nf = _wiz_finding("wiz-1")
    res1 = process_snapshot(
        session,
        source=WIZ_SOURCE,
        poll_id=poll1,
        raw_uri="file:///wiz1.json",
        findings=[nf],
        owner_resolver=lambda _s, _a, _t: "unowned",
        auto_close_threshold=3,
    )
    assert res1.inserted == 1
    session.commit()

    for _ in range(3):
        process_snapshot(
            session,
            source=WIZ_SOURCE,
            poll_id=uuid4(),
            raw_uri="file:///empty.json",
            findings=[],
            owner_resolver=lambda _s, _a, _t: "unowned",
            auto_close_threshold=3,
        )
        session.commit()

    row = session.get(Finding, nf.id)
    assert row is not None
    assert row.status == Status.auto_closed
    assert row.consecutive_misses >= 3


def test_wiz_category_restamp_on_update(session) -> None:
    poll1 = uuid4()
    nf = _wiz_finding("wiz-cat", category="issue")
    process_snapshot(
        session,
        source=WIZ_SOURCE,
        poll_id=poll1,
        raw_uri="file:///wiz.json",
        findings=[nf],
        owner_resolver=lambda _s, _a, _t: "unowned",
        auto_close_threshold=3,
    )
    row = session.get(Finding, nf.id)
    assert row.wiz_category == "issue"

    nf2 = map_node(
        {
            "id": "wiz-cat",
            "severity": "HIGH",
            "applicationServices": [{"displayName": "unknown-service"}],
        },
        "cloud_config",
    )
    process_snapshot(
        session,
        source=WIZ_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///wiz2.json",
        findings=[nf2],
        owner_resolver=lambda _s, _a, _t: "unowned",
        auto_close_threshold=3,
    )
    session.refresh(row)
    assert row.wiz_category == "cloud_config"
    assert row.severity == Severity.high
