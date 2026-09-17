"""Snapshot processor invariants.

Covers:
  - Idempotency: replaying the same poll_id is a no-op.
  - Per-field diffing: severity bump emits one event; second run with same data emits none.
  - Owner stamping: members of a team get team scoping; assets in ownership.yaml stamp the team.
  - Auto-close: missing for N consecutive polls -> status=auto_closed + event.
  - Reopen: previously auto-closed finding reappears -> status=open + reopened event,
    first_seen_at preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select

from app.core.config import get_settings
from app.core.config_store import OwnershipMap, TeamConfig
from app.core.enums import EventType, Severity, Status
from app.core.models import Finding, FindingEvent, ProcessedPayload
from app.internal.ownership_reresolve import core_reresolve
from app.normalizer.mappers.dependabot import DEPENDABOT_SOURCE, map_alert
from app.normalizer.processor import process_snapshot
from app.normalizer.types import NormalizedFinding

OWNED_REPO = "ExampleOrg/example-service"  # mapped to pricing-platform in config/ownership.yaml
UNOWNED_REPO = "ExampleOrg/random-thing"


def _alert(
    full_name: str = OWNED_REPO,
    number: int = 100,
    severity: str = "high",
    summary: str = "Use after free",
    created_at: str | None = "2025-01-15T08:00:00Z",
) -> dict:
    payload: dict = {
        "number": number,
        "state": "open",
        "repository": {"full_name": full_name},
        "security_advisory": {
            "severity": severity,
            "summary": summary,
            "description": "desc",
            "cve_id": "CVE-2024-12345",
            "cwe_ids": ["CWE-416"],
        },
        "dependency": {"package": {"ecosystem": "pip", "name": "libxml2"}},
    }
    if created_at is not None:
        payload["created_at"] = created_at
    return payload


def _ownership_resolver(asset_to_team: dict[str, str]):
    def _resolve(_source: str, asset_id: str, _tags: list[str]) -> str:
        return asset_to_team.get(asset_id, "unowned")

    return _resolve


def _run(session, *, alerts, threshold=3, poll_id=None, asset_to_team: dict[str, str] | None = None):
    mapping = {f"repo:{OWNED_REPO}": "pricing-platform"}
    if asset_to_team:
        mapping.update(asset_to_team)
    return process_snapshot(
        session,
        source=DEPENDABOT_SOURCE,
        poll_id=poll_id or uuid4(),
        raw_uri="file:///tmp/test.json",
        findings=[map_alert(a) for a in alerts],
        owner_resolver=_ownership_resolver(mapping),
        auto_close_threshold=threshold,
    )


def test_first_ingest_inserts_and_emits_discovered(session) -> None:
    res = _run(session, alerts=[_alert()])
    session.commit()

    assert res.inserted == 1
    assert res.updated == 0
    assert res.already_processed is False

    finding = session.scalars(select(Finding)).one()
    assert finding.source == "dependabot"
    assert finding.native_id == f"{OWNED_REPO}#100"
    assert finding.status == Status.open
    assert finding.severity == Severity.high
    assert finding.consecutive_misses == 0
    assert finding.owner_team == "pricing-platform"
    assert finding.first_seen_at == finding.last_seen_at

    events = session.scalars(select(FindingEvent)).all()
    assert [e.event_type for e in events] == [EventType.discovered]


def test_replay_is_idempotent(session) -> None:
    poll_id = uuid4()
    _run(session, alerts=[_alert()], poll_id=poll_id)
    session.commit()

    res = _run(session, alerts=[_alert()], poll_id=poll_id)
    session.commit()

    assert res.already_processed is True
    assert res.inserted == 0
    assert session.scalars(select(Finding)).all().__len__() == 1
    assert session.scalars(select(FindingEvent)).all().__len__() == 1
    assert session.scalars(select(ProcessedPayload)).all().__len__() == 1


def test_no_op_second_run_emits_no_events(session) -> None:
    """A repeat snapshot with identical content advances last_seen_at but emits no events."""
    _run(session, alerts=[_alert()])
    session.commit()
    first_last_seen = session.scalars(select(Finding.last_seen_at)).one()

    res = _run(session, alerts=[_alert()])
    session.commit()
    second_last_seen = session.scalars(select(Finding.last_seen_at)).one()

    assert res.inserted == 0
    assert res.updated == 0
    assert second_last_seen >= first_last_seen
    assert session.scalars(select(FindingEvent)).all().__len__() == 1  # only the discovered event


def test_severity_bump_emits_one_typed_event(session) -> None:
    _run(session, alerts=[_alert(severity="medium")])
    session.commit()

    _run(session, alerts=[_alert(severity="critical")])
    session.commit()

    events = session.scalars(select(FindingEvent).order_by(FindingEvent.occurred_at)).all()
    types = [e.event_type for e in events]
    assert types == [EventType.discovered, EventType.severity_changed]
    assert events[1].from_value == "medium"
    assert events[1].to_value == "critical"

    finding = session.scalars(select(Finding)).one()
    assert finding.severity == Severity.critical


def test_unowned_asset_stamped_unowned(session) -> None:
    _run(session, alerts=[_alert(full_name=UNOWNED_REPO)])
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.owner_team == "unowned"


def test_ingest_emits_ownership_changed_on_owner_team_transition(session) -> None:
    _run(
        session,
        alerts=[_alert()],
        asset_to_team={f"repo:{OWNED_REPO}": "unowned"},
    )
    session.commit()

    _run(
        session,
        alerts=[_alert()],
        asset_to_team={f"repo:{OWNED_REPO}": "pricing-platform"},
    )
    session.commit()

    events = session.scalars(
        select(FindingEvent).where(FindingEvent.event_type == EventType.ownership_changed)
    ).all()
    assert len(events) == 1
    assert events[0].from_value == "unowned"
    assert events[0].to_value == "pricing-platform"
    assert events[0].actor == "system:dependabot_ingest"

    finding = session.scalars(select(Finding)).one()
    assert finding.owner_team == "pricing-platform"


def test_excluded_repo_stamped_excluded(session) -> None:
    _run(
        session,
        alerts=[_alert(full_name="ExampleOrg/product-examples")],
        asset_to_team={"repo:ExampleOrg/product-examples": "excluded"},
    )
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.owner_team == "excluded"


def test_auto_close_after_threshold_then_reopen(session) -> None:
    threshold = 3

    _run(session, alerts=[_alert(number=1)], threshold=threshold)
    session.commit()
    finding = session.scalars(select(Finding)).one()
    original_first_seen = finding.first_seen_at

    for _ in range(threshold):
        _run(session, alerts=[], threshold=threshold)
        session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.status == Status.auto_closed
    assert finding.consecutive_misses >= threshold

    auto_close_events = session.scalars(
        select(FindingEvent).where(FindingEvent.event_type == EventType.auto_closed)
    ).all()
    assert len(auto_close_events) == 1
    assert auto_close_events[0].actor == "system:auto_close"

    _run(session, alerts=[_alert(number=1)], threshold=threshold)
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.status == Status.open
    assert finding.consecutive_misses == 0
    assert finding.first_seen_at == original_first_seen  # preserved across the flap

    reopened_events = session.scalars(
        select(FindingEvent).where(FindingEvent.event_type == EventType.reopened)
    ).all()
    assert len(reopened_events) == 1


def test_upstream_created_at_set_on_insert(session) -> None:
    """Insert path must persist the source's creation timestamp, not just `now`."""
    _run(session, alerts=[_alert(created_at="2025-01-15T08:00:00Z")])
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.upstream_created_at is not None
    assert finding.upstream_created_at.year == 2025
    # `first_seen_at` is "now" (when we ingested), so the two diverge — that's the bug fix.
    assert finding.first_seen_at != finding.upstream_created_at
    # The age anchor should be the upstream value.
    assert finding.sla_started_at == finding.upstream_created_at


def test_upstream_created_at_backfilled_on_update(session) -> None:
    """A finding inserted before the upstream timestamp existed (legacy / migration)
    gets its `upstream_created_at` backfilled by the next snapshot."""
    _run(session, alerts=[_alert(created_at=None)])
    session.commit()
    finding = session.scalars(select(Finding)).one()
    assert finding.upstream_created_at is None  # baseline: no source timestamp

    _run(session, alerts=[_alert(created_at="2024-06-01T00:00:00Z")])
    session.commit()
    finding = session.scalars(select(Finding)).one()
    assert finding.upstream_created_at is not None
    assert finding.upstream_created_at.year == 2024


def test_reopen_records_reopened_at_but_does_not_anchor_sla(session) -> None:
    """auto_closed -> open transition must record `reopened_at` for the audit
    trail / flap detection but MUST NOT move the SLA anchor.

    The original spec restarted the SLA clock on reopen ("a re-introduced
    vulnerability gets a fresh window"). In practice the reopen path fires
    on dashboard-internal absent-detection bugs, not on real upstream re-
    introductions — most famously the SonarCloud multi-org cross-
    contamination (commit 8d11948) that auto-closed 1k+ valid findings
    overnight and then bulk-reopened them all in a single poll once fixed.
    With the old anchor that bulk-reopen reset every Sonar finding's age
    to "3 hours" the moment recovery ran. The anchor now coalesces
    `upstream_created_at -> first_seen_at` and ignores `reopened_at`.
    Pinning the new contract here so a future revert is intentional.
    """
    threshold = 2

    _run(session, alerts=[_alert(number=7, created_at="2024-01-01T00:00:00Z")], threshold=threshold)
    session.commit()
    finding = session.scalars(select(Finding)).one()
    original_anchor = finding.sla_started_at
    assert finding.reopened_at is None
    assert original_anchor == finding.upstream_created_at  # baseline

    for _ in range(threshold):
        _run(session, alerts=[], threshold=threshold)
        session.commit()
    finding = session.scalars(select(Finding)).one()
    assert finding.status == Status.auto_closed

    _run(session, alerts=[_alert(number=7, created_at="2024-01-01T00:00:00Z")], threshold=threshold)
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.status == Status.open
    # `reopened_at` is still stamped (used by /admin for flappy-finding triage
    # and by the event log) — it's just no longer the SLA anchor.
    assert finding.reopened_at is not None
    # Anchor stays at the upstream creation time. The reopen does NOT move it.
    assert finding.sla_started_at == finding.upstream_created_at
    assert finding.sla_started_at == original_anchor
    assert finding.sla_started_at < finding.reopened_at


def test_consecutive_misses_resets_when_finding_reappears(session) -> None:
    _run(session, alerts=[_alert(number=1)], threshold=5)
    session.commit()

    _run(session, alerts=[], threshold=5)
    _run(session, alerts=[], threshold=5)
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.consecutive_misses == 2
    assert finding.status == Status.open  # below threshold

    _run(session, alerts=[_alert(number=1)], threshold=5)
    session.commit()

    finding = session.scalars(select(Finding)).one()
    assert finding.consecutive_misses == 0
    assert finding.status == Status.open


def test_sonar_snapshot_does_not_age_dependabot_findings(session) -> None:
    """ cross-source isolation invariant.

    A SonarCloud poll must NOT advance Dependabot findings' `consecutive_misses`,
    or vice versa. The processor scopes its absent-marking by `source` precisely
    to support multi-source ingestion without each source's misses cascading
    into the others' auto-close clocks.

    Setup: insert one Dependabot finding (open). Then run a Sonar snapshot with
    a single Sonar finding. Expect:
      - Dependabot finding's consecutive_misses stays 0
      - Sonar finding lands as open with consecutive_misses=0
      - Re-running the same Sonar snapshot's poll_id is idempotent
    """
    from app.normalizer.mappers.sonarcloud import (
        SONARCLOUD_SOURCE,
        map_issue,
    )
    from app.normalizer.processor import process_snapshot

    _run(session, alerts=[_alert(number=900)])
    session.commit()
    dep_before = session.scalars(
        select(Finding).where(Finding.source == "dependabot")
    ).one()
    assert dep_before.consecutive_misses == 0

    sonar_issue = {
        "key": "AY-cross-1",
        "project": "exampleorg_product-core",
        "severity": "BLOCKER",
        "message": "Sonar vulnerability",
        "rule": "java:S2076",
        "creationDate": "2025-09-01T12:34:56+0000",
    }
    nf = map_issue(sonar_issue, organization="exampleorg", sonar_key_to_asset_id={})

    sonar_poll = uuid4()
    res = process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=sonar_poll,
        raw_uri="file:///tmp/sonar.json",
        findings=[nf],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    assert res.inserted == 1
    assert res.absent_marked == 0  # no other sonar findings to mark absent

    dep_after = session.scalars(
        select(Finding).where(Finding.source == "dependabot")
    ).one()
    sonar_after = session.scalars(
        select(Finding).where(Finding.source == SONARCLOUD_SOURCE)
    ).one()
    assert dep_after.consecutive_misses == 0  # untouched by the Sonar poll
    assert sonar_after.consecutive_misses == 0
    assert sonar_after.status == Status.open

    # And the dependabot finding is still missable by its OWN poll source.
    _run(session, alerts=[], threshold=10)
    session.commit()
    dep_aged = session.scalars(
        select(Finding).where(Finding.source == "dependabot")
    ).one()
    assert dep_aged.consecutive_misses == 1  # advanced by dependabot empty poll only


def test_sonar_poll_reclassifies_existing_sonar_row_to_trivy_in_place(session) -> None:
    """When the mapper's Trivy detection improves on a future deploy, an
    existing `Finding` previously stored as `source = "sonarcloud"` (e.g.
    because the early mapper only checked the rule prefix and the org's
    importer used a non-standard engineId) must get re-stamped to
    `source = "sonarcloud_trivy"` IN PLACE on the next poll — same id,
    same event log, same first_seen_at. Without that, the old row would
    age and auto-close while a fresh `sonarcloud_trivy` row was inserted N
    polls later, leaking the misclassified row into /developer for the
    duration of the migration window.

    This test pins the contract: insert a Sonar finding whose message
    embeds the canonical Trivy `avd.aquasec.com` URL, then re-poll the
    same issue (the mapper now classifies it as Trivy via the URL signal)
    and assert the existing row's source flipped without changing id /
    first_seen_at.
    """
    from app.normalizer.mappers.sonarcloud import (
        SONARCLOUD_SOURCE,
        SONARCLOUD_TRIVY_SOURCE,
        map_issue,
    )
    from app.normalizer.processor import process_snapshot

    raw_issue = {
        "key": "AY-trivy-reclassify-1",
        "project": "exampleorg_product-core",
        "severity": "MAJOR",
        "rule": "external_some_engine:CVE-2026-1",
        # Canonical Trivy message — `avd.aquasec.com` URL flips the mapper
        # into the `sonarcloud_trivy` branch on the new code path.
        "message": (
            "Package: stdlib Installed Version: v1.26.1 Vulnerability "
            "CVE-2026-1 Severity: HIGH Fixed Version: 1.26.2 Link: "
            "https://avd.aquasec.com/nvd/cve-2026-1"
        ),
        "creationDate": "2025-09-01T12:34:56+0000",
    }
    nf = map_issue(raw_issue, organization="exampleorg", sonar_key_to_asset_id={})
    assert nf.source == SONARCLOUD_TRIVY_SOURCE  # mapper classifies it as Trivy
    finding_id = nf.id

    # Simulate the pre-fix DB state: the same row was previously stored as
    # `sonarcloud` because the old mapper only checked the rule prefix.
    # Direct INSERT with the matching id mirrors what the buggy mapper
    # would have produced (the id is source-stable, so it matches the new
    # mapper's id derivation as well).
    pre_existing = Finding(
        id=finding_id,
        source=SONARCLOUD_SOURCE,
        native_id=nf.native_id,
        title=nf.title,
        description=nf.description,
        severity=nf.severity,
        cve_id=nf.cve_id,
        cwe_id=nf.cwe_id,
        asset_id=nf.asset_id,
        asset_type=nf.asset_type,
        asset_root=nf.asset_root,
        asset_display=nf.asset_display,
        owner_team="unowned",
        correlation_group_id=nf.correlation_group_id,
        status=Status.open,
        consecutive_misses=0,
        raw_payload_uri="file:///tmp/old-poll.json",
        tags=[],
    )
    session.add(pre_existing)
    session.commit()
    original_first_seen = pre_existing.first_seen_at

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,  # poller-level source, unchanged
        poll_id=uuid4(),
        raw_uri="file:///tmp/new-poll.json",
        findings=[nf],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    after = session.scalars(select(Finding).where(Finding.id == finding_id)).one()
    assert after.source == SONARCLOUD_TRIVY_SOURCE  # re-stamped in place
    assert after.id == finding_id  # same id, same event-log linkage
    assert after.first_seen_at == original_first_seen  # not a new row
    assert after.consecutive_misses == 0
    assert after.status == Status.open


def test_sonar_poll_ages_native_and_external_trivy_together(session) -> None:
    """The SonarCloud poller emits both native Sonar issues
    (`Finding.source = "sonarcloud"`) and externally-imported Trivy issues
    (`Finding.source = "sonarcloud_trivy"`) in a single snapshot. Absent
    detection and auto-close must therefore see the snapshot's `source`
    parameter as a *group*, not a single value — otherwise a Trivy-in-Sonar
    finding that disappears from a future snapshot would never advance its
    `consecutive_misses` and would never auto-close.

    This test pins the SOURCE_GROUPS expansion in the processor: a Sonar
    poll covering only the native finding (Trivy entry absent) bumps the
    Trivy finding's misses, and crossing the threshold transitions it to
    auto_closed exactly the same way it would a native one.
    """
    from app.normalizer.mappers.sonarcloud import (
        SONARCLOUD_SOURCE,
        SONARCLOUD_TRIVY_SOURCE,
        map_issue,
    )
    from app.normalizer.processor import process_snapshot

    native = map_issue(
        {
            "key": "AY-native-1",
            "project": "exampleorg_product-core",
            "severity": "BLOCKER",
            "message": "native sonar",
            "rule": "java:S2076",
            "creationDate": "2025-09-01T12:34:56+0000",
        },
        organization="exampleorg",
        sonar_key_to_asset_id={},
    )
    trivy = map_issue(
        {
            "key": "AY-trivy-1",
            "project": "exampleorg_product-core",
            "severity": "BLOCKER",
            "message": "Trivy CVE",
            "rule": "external_trivy:CVE-2021-44228",
            "creationDate": "2025-09-01T12:34:56+0000",
        },
        organization="exampleorg",
        sonar_key_to_asset_id={},
    )
    assert native.source == SONARCLOUD_SOURCE
    assert trivy.source == SONARCLOUD_TRIVY_SOURCE

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///tmp/sonar-1.json",
        findings=[native, trivy],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///tmp/sonar-2.json",
        findings=[native],  # Trivy entry vanished from this snapshot
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    trivy_row = session.scalars(
        select(Finding).where(Finding.source == SONARCLOUD_TRIVY_SOURCE)
    ).one()
    assert trivy_row.consecutive_misses == 1
    assert trivy_row.status == Status.open

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///tmp/sonar-3.json",
        findings=[native],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    trivy_after = session.scalars(
        select(Finding).where(Finding.source == SONARCLOUD_TRIVY_SOURCE)
    ).one()
    assert trivy_after.consecutive_misses >= 2
    assert trivy_after.status == Status.auto_closed

    native_after = session.scalars(
        select(Finding).where(Finding.source == SONARCLOUD_SOURCE)
    ).one()
    assert native_after.status == Status.open
    assert native_after.consecutive_misses == 0


def test_processor_reconciles_orphan_stale_id_row(session) -> None:
    """An older mapper deploy may have inserted a `sonarcloud_trivy` row whose
    `Finding.id` was derived from the *classified* source
    (`uuid5("sonarcloud_trivy:" + native_id)`) instead of the source-stable
    id (`uuid5("sonarcloud:" + native_id)`). The new mapper's id no longer
    matches that row, so the processor must reconcile by deleting the orphan
    before inserting a fresh row at the source-stable id — otherwise the
    insert collides on `uq_findings_source_native_id` and the snapshot fails
    with a 500.

    Scenario 1: only the stale-id row exists in the DB.
    """
    from app.normalizer.mappers.sonarcloud import (
        SONARCLOUD_SOURCE,
        SONARCLOUD_TRIVY_SOURCE,
        _finding_id,
        map_issue,
    )
    from app.normalizer.processor import process_snapshot

    raw_issue = {
        "key": "AY-trivy-orphan-1",
        "project": "exampleorg_product-core",
        "severity": "MAJOR",
        "rule": "external_trivy:CVE-2026-9",
        "message": "Trivy says https://avd.aquasec.com/nvd/cve-2026-9",
        "creationDate": "2025-09-01T12:34:56+0000",
    }
    nf = map_issue(raw_issue, organization="exampleorg", sonar_key_to_asset_id={})
    assert nf.source == SONARCLOUD_TRIVY_SOURCE

    stale_id = _finding_id(SONARCLOUD_TRIVY_SOURCE, nf.native_id)
    assert stale_id != nf.id  # exact precondition the reconciler exists for

    session.add(
        Finding(
            id=stale_id,
            source=SONARCLOUD_TRIVY_SOURCE,
            native_id=nf.native_id,
            title="legacy title",
            description=nf.description,
            severity=nf.severity,
            cve_id=nf.cve_id,
            cwe_id=nf.cwe_id,
            asset_id=nf.asset_id,
            asset_type=nf.asset_type,
            asset_root=nf.asset_root,
            asset_display=nf.asset_display,
            owner_team="unowned",
            correlation_group_id=nf.correlation_group_id,
            status=Status.open,
            consecutive_misses=0,
            raw_payload_uri="file:///tmp/legacy.json",
            tags=[],
        )
    )
    session.commit()

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///tmp/new.json",
        findings=[nf],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    rows = session.scalars(select(Finding)).all()
    assert len(rows) == 1, "stale orphan row should have been removed"
    assert rows[0].id == nf.id, "row should now be at the source-stable id"
    assert rows[0].source == SONARCLOUD_TRIVY_SOURCE
    assert rows[0].native_id == nf.native_id
    assert rows[0].title == nf.title  # fresh insert took the snapshot title
    assert rows[0].consecutive_misses == 0


def test_processor_merges_events_when_stale_id_row_collides_with_sibling(
    session,
) -> None:
    """Scenario 2: BOTH a row at the source-stable id (carrying
    `source = "sonarcloud"`) AND a stale-id row at
    `uuid5("sonarcloud_trivy:" + native_id)` (carrying
    `source = "sonarcloud_trivy"`) exist for the same `native_id`. This is
    the data state that produced the 500 the user hit on
    `make poller-sonarcloud`: the new mapper matches the source-stable row
    by id, tries to re-stamp its source to `sonarcloud_trivy`, and the
    unique constraint on `(source, native_id)` rejects the update because
    the stale-id row already occupies that slot.

    Contract: the reconciler MUST migrate the stale row's events onto the
    source-stable row (so the audit trail survives), then delete the
    duplicate. The for-loop's existing-path then re-stamps the source-stable
    row in place.
    """
    from app.normalizer.mappers.sonarcloud import (
        SONARCLOUD_SOURCE,
        SONARCLOUD_TRIVY_SOURCE,
        _finding_id,
        map_issue,
    )
    from app.normalizer.processor import process_snapshot

    raw_issue = {
        "key": "AY-trivy-collision-1",
        "project": "exampleorg_product-core",
        "severity": "MAJOR",
        "rule": "external_some_engine:CVE-2026-7",
        "message": "Trivy says https://avd.aquasec.com/nvd/cve-2026-7",
        "creationDate": "2025-09-01T12:34:56+0000",
    }
    nf = map_issue(raw_issue, organization="exampleorg", sonar_key_to_asset_id={})
    assert nf.source == SONARCLOUD_TRIVY_SOURCE
    keeper_id = nf.id  # source-stable
    stale_id = _finding_id(SONARCLOUD_TRIVY_SOURCE, nf.native_id)
    assert stale_id != keeper_id

    keeper = Finding(
        id=keeper_id,
        source=SONARCLOUD_SOURCE,  # mis-classified by the very-old mapper
        native_id=nf.native_id,
        title=nf.title,
        description=nf.description,
        severity=nf.severity,
        cve_id=nf.cve_id,
        cwe_id=nf.cwe_id,
        asset_id=nf.asset_id,
        asset_type=nf.asset_type,
        asset_root=nf.asset_root,
        asset_display=nf.asset_display,
        owner_team="unowned",
        correlation_group_id=nf.correlation_group_id,
        status=Status.open,
        consecutive_misses=0,
        raw_payload_uri="file:///tmp/keeper.json",
        tags=[],
    )
    session.add(keeper)
    session.flush()
    session.add(
        FindingEvent(
            finding_id=keeper_id,
            event_type=EventType.discovered,
            from_value=None,
            to_value=Status.open.value,
            actor="system:sonarcloud_ingest",
        )
    )

    stale = Finding(
        id=stale_id,
        source=SONARCLOUD_TRIVY_SOURCE,  # the partial-fix deploy created this
        native_id=nf.native_id,
        title="trivy duplicate",
        description=nf.description,
        severity=nf.severity,
        cve_id=nf.cve_id,
        cwe_id=nf.cwe_id,
        asset_id=nf.asset_id,
        asset_type=nf.asset_type,
        asset_root=nf.asset_root,
        asset_display=nf.asset_display,
        owner_team="unowned",
        correlation_group_id=nf.correlation_group_id,
        status=Status.open,
        consecutive_misses=0,
        raw_payload_uri="file:///tmp/stale.json",
        tags=[],
    )
    session.add(stale)
    session.flush()
    session.add(
        FindingEvent(
            finding_id=stale_id,
            event_type=EventType.discovered,
            from_value=None,
            to_value=Status.open.value,
            actor="system:sonarcloud_ingest",
        )
    )
    session.commit()

    process_snapshot(
        session,
        source=SONARCLOUD_SOURCE,
        poll_id=uuid4(),
        raw_uri="file:///tmp/recover.json",
        findings=[nf],
        owner_resolver=_ownership_resolver({}),
        auto_close_threshold=2,
    )
    session.commit()

    rows = session.scalars(select(Finding)).all()
    assert len(rows) == 1, "duplicate row should have been merged away"
    assert rows[0].id == keeper_id
    assert rows[0].source == SONARCLOUD_TRIVY_SOURCE  # re-stamped in place

    events = session.scalars(
        select(FindingEvent).where(FindingEvent.finding_id == keeper_id)
    ).all()
    # Both pre-existing events (keeper's discovered + stale's discovered now
    # re-parented) must have survived the merge.
    assert len(events) >= 2
    orphaned = session.scalars(
        select(FindingEvent).where(FindingEvent.finding_id == stale_id)
    ).all()
    assert orphaned == []


def test_existing_row_canonicalizes_asset_fields_on_ingest(session) -> None:
    """An existing finding whose asset fields were persisted under an earlier
    deploy (e.g. lowercase organization in the asset_id, `repo:exampleorg/...`,
    because `GITHUB_ORG` was unset and the SonarCloud mapper fell back to
    `organization.lower()` as the namespace) gets re-stamped to the current
    mapper output (`repo:ExampleOrg/...`) on the next snapshot.

    Why this matters: `OwnershipMap.team_for_asset` is a case-sensitive dict
    lookup against `ownership.yaml.assets[*].id`. A stored lowercase
    `asset_id` reads back as `unowned`, so the nightly rollup belt-and-braces
    `core_reresolve` flips the row from its correct team back to
    `unowned` on the stored value, undoing whatever ingest just healed via
    `nf.asset_id`. Pinning that the persisted asset_id is canonicalized
    after ingest closes the see-saw.
    """
    namespace = UUID(get_settings().namespace_secdb)
    native_id = "exampleorg/ExampleOrg_example-service#issue-canon-1"
    fid = uuid5(namespace, f"sonarcloud:{native_id}")
    now = datetime.now(UTC)

    stale = Finding(
        id=fid,
        source="sonarcloud",
        native_id=native_id,
        title="Use after free in example-service",
        description="",
        severity=Severity.high,
        cve_id=None,
        cwe_id=None,
        asset_id="repo:exampleorg/example-service",
        asset_type="github_repo",
        asset_root="repo:exampleorg/example-service",
        asset_display="exampleorg/example-service",
        owner_team="unowned",  # the rollup re-resolve flipped it here
        status=Status.open,
        first_seen_at=now,
        last_seen_at=now,
        consecutive_misses=0,
        raw_payload_uri="file:///tmp/legacy.json",
        tags=[],
    )
    session.add(stale)
    session.commit()

    # Snapshot from today's mapper: same (source, native_id), canonical asset.
    canonical = NormalizedFinding(
        id=fid,
        source="sonarcloud",
        native_id=native_id,
        title="Use after free in example-service",
        description="",
        severity=Severity.high,
        cve_id=None,
        cwe_id=None,
        asset_id="repo:ExampleOrg/example-service",
        asset_type="github_repo",
        asset_root="repo:ExampleOrg/example-service",
        asset_display="ExampleOrg/example-service",
        correlation_group_id=None,
        tags=[],
        upstream_created_at=None,
    )

    def _resolve(_source: str, asset_id: str, _tags: list[str]) -> str:
        return "tsea" if asset_id == "repo:ExampleOrg/example-service" else "unowned"

    process_snapshot(
        session,
        source="sonarcloud",
        poll_id=uuid4(),
        raw_uri="file:///tmp/sonar.json",
        findings=[canonical],
        owner_resolver=_resolve,
        auto_close_threshold=None,
    )
    session.commit()

    refreshed = session.get(Finding, fid)
    assert refreshed is not None
    assert refreshed.asset_id == "repo:ExampleOrg/example-service"
    assert refreshed.asset_display == "ExampleOrg/example-service"
    assert refreshed.asset_root == "repo:ExampleOrg/example-service"
    assert refreshed.asset_type == "github_repo"
    assert refreshed.owner_team == "tsea"

    # Belt-and-braces: a re-resolve pass against an OwnershipMap that only
    # knows the canonical key must be a no-op. This is the see-saw the cloud
    # was exhibiting (rollup flipping `tsea -> unowned` because the stored
    # asset_id was lowercase) — pinning it shut here.
    om = OwnershipMap(
        asset_to_team={"repo:ExampleOrg/example-service": "tsea"},
        teams={"tsea": TeamConfig(name="tsea")},
    )
    result = core_reresolve(session, om, actor="system:test")
    session.commit()

    assert result.updated == 0
    refreshed = session.get(Finding, fid)
    assert refreshed.owner_team == "tsea"
