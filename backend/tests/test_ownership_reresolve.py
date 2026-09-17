"""Ownership re-resolution."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import select

from app.core.config_store import get_config_cache
from app.core.enums import EventType, Severity
from app.core.models import Finding, FindingEvent
from app.internal.ownership_reresolve import core_reresolve
from tests._factory import make_finding


def test_reresolve_updates_and_emits_event(session) -> None:
    f = make_finding(
        session,
        native_id="reresolve#1",
        owner_team="unowned",
        asset_id="repo:ExampleOrg/example-service",
        severity=Severity.high,
    )
    session.commit()

    ownership = get_config_cache().get_ownership()
    result = core_reresolve(session, ownership, actor="system:test")
    session.commit()

    assert result.updated == 1
    session.expire_all()
    refreshed = session.get(Finding, f.id)
    assert refreshed is not None
    assert refreshed.owner_team == "pricing-platform"

    events = session.execute(
        select(FindingEvent).where(
            FindingEvent.finding_id == f.id,
            FindingEvent.event_type == EventType.ownership_changed,
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].from_value == "unowned"
    assert events[0].to_value == "pricing-platform"
    assert events[0].actor == "system:test"


def test_reresolve_noop_when_already_correct(session) -> None:
    make_finding(
        session,
        native_id="reresolve#noop",
        owner_team="pricing-platform",
        asset_id="repo:ExampleOrg/example-service",
    )
    session.commit()

    ownership = get_config_cache().get_ownership()
    result = core_reresolve(session, ownership, actor="system:test")
    assert result.updated == 0


def test_reresolve_dry_run_writes_nothing(session) -> None:
    f = make_finding(
        session,
        native_id="reresolve#dry",
        owner_team="unowned",
        asset_id="repo:ExampleOrg/example-service",
    )
    session.commit()

    ownership = get_config_cache().get_ownership()
    result = core_reresolve(session, ownership, actor="system:test", dry_run=True)
    session.commit()

    assert result.updated == 1
    refreshed = session.get(Finding, f.id)
    assert refreshed.owner_team == "unowned"
    count = session.execute(
        select(FindingEvent).where(
            FindingEvent.finding_id == f.id,
            FindingEvent.event_type == EventType.ownership_changed,
        )
    ).scalars().all()
    assert len(count) == 0


def test_reresolve_excluded_transition(session, monkeypatch) -> None:
    """Moving to excluded emits ownership_changed like any other team change."""
    from app.core.config_store import OwnershipMap, TeamConfig

    om = OwnershipMap(
        asset_to_team={"repo:ExampleOrg/product-sandbox": "pin"},
        teams={"pin": TeamConfig(name="pin"), "unowned": TeamConfig(name="unowned")},
        excluded_repos=frozenset({"product-sandbox"}),
    )
    f = make_finding(
        session,
        native_id="ExampleOrg/product-sandbox#1",
        asset_id="repo:ExampleOrg/product-sandbox",
        owner_team="unowned",
    )
    session.commit()

    result = core_reresolve(session, om, actor="system:test")
    session.commit()

    assert result.updated == 1
    refreshed = session.get(Finding, f.id)
    assert refreshed.owner_team == "excluded"


def test_reresolve_preserves_wiz_cloud_platform_owner(session) -> None:
    """Rollup pre-step must not clobber CPE from platform_pillar:product cloud resources."""
    f = make_finding(
        session,
        native_id="wiz:cloud-issue-1",
        source="wiz",
        owner_team="product-platform",
        asset_id="cloudres:GCP/example-production-project/func-1",
        severity=Severity.high,
        tags=["platform_pillar:product", "wiz_category:issue"],
    )
    session.flush()
    session.query(Finding).filter_by(id=f.id).one().wiz_category = "issue"
    session.commit()

    ownership = get_config_cache().get_ownership()
    result = core_reresolve(session, ownership, actor="system:test")
    session.commit()

    assert result.updated == 0
    refreshed = session.get(Finding, f.id)
    assert refreshed.owner_team == "product-platform"


def test_reresolve_stamps_wiz_cloud_from_platform_pillar_tag(session) -> None:
    f = make_finding(
        session,
        native_id="wiz:cloud-issue-2",
        source="wiz",
        owner_team="unowned",
        asset_id="cloudres:GCP/example-production-project/func-2",
        severity=Severity.high,
        tags=["platform_pillar:product"],
    )
    session.commit()

    ownership = get_config_cache().get_ownership()
    result = core_reresolve(session, ownership, actor="system:test")
    session.commit()

    assert result.updated == 1
    assert session.get(Finding, f.id).owner_team == "product-platform"


def test_maybe_trigger_rollup_backfill_async() -> None:
    with patch("app.internal.ownership_reresolve.get_settings") as gs:
        settings = gs.return_value
        settings.ingest_transport = "pubsub"
        settings.gcp_region = "europe-west1"
        settings.pubsub_project = "test-project"
        settings.rollup_job = "secdb-rollup"
        with patch("app.internal.cloud_run_jobs.run_cloud_run_job") as run_job:
            run_job.return_value = "projects/p/locations/r/jobs/rollup/executions/e1"
            from app.internal.ownership_reresolve import maybe_trigger_rollup_backfill

            triggered = maybe_trigger_rollup_backfill(3, async_mode=True)
    assert triggered is True
    run_job.assert_called_once()
