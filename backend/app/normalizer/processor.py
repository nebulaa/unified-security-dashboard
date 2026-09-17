"""Snapshot processor — the per-poll DB transaction.

Single function `process_snapshot()` runs the full ingest cycle for one snapshot of one
source. It is idempotent (replay-safe) via `processed_payloads`.

Order of operations inside the caller's DB transaction:

  1. INSERT processed_payloads(source, poll_id) -- conflict ⇒ already processed
  2. UPSERT each finding present in the snapshot:
       - new                ⇒ insert + emit `discovered`, set first_seen_at = now
       - reopened           ⇒ status auto_closed -> open + emit `reopened`,
                              first_seen_at preserved
       - per-field changed  ⇒ emit one typed event per (severity / status / title /
                              description) change
       - always             ⇒ last_seen_at = now, consecutive_misses = 0
  3. ABSENT findings of the same source (still in an open status):
       - consecutive_misses += 1 (bulk UPDATE, no events)
  4. Findings whose consecutive_misses crossed the source's threshold and are still
     in an open status: status -> auto_closed, emit `auto_closed`.
  5. Caller commits.

: owner_team is stamped from the cached ownership map; ingest emits
`ownership_changed` when an existing row's resolved team changes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.enums import EventType, Status
from app.core.models import Finding, FindingEvent, ProcessedPayload
from app.normalizer.types import NormalizedFinding

log = structlog.get_logger("secdb.normalizer")

UNOWNED_TEAM = "unowned"

# Per-poller -> set of Finding.source values it can produce. A snapshot from the
# poller named on the left contains findings whose `source` is one of the values
# on the right; absent-detection and auto-close therefore look across the whole
# set rather than the poller name alone. Today this exists only for SonarCloud:
# the SonarCloud poller surfaces both native Sonar rule violations
# (Finding.source = "sonarcloud") and externally-imported Trivy issues
# (Finding.source = "sonarcloud_trivy") in a single `/api/issues/search`
# response, and we want a Trivy finding that disappears from a future snapshot
# to age and auto-close just like a native one. Default for any source not
# listed here is `{source}` (the legacy single-source behaviour).
SOURCE_GROUPS: dict[str, frozenset[str]] = {
    "sonarcloud": frozenset({"sonarcloud", "sonarcloud_trivy"}),
}


@dataclass
class SnapshotResult:
    already_processed: bool
    inserted: int
    updated: int
    reopened: int
    auto_closed: int
    absent_marked: int
    finding_count: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _record_processed(
    session: Session, source: str, poll_id: UUID, raw_uri: str, finding_count: int
) -> bool:
    """Insert the idempotency row. Returns True if newly inserted, False if already present."""
    stmt = (
        pg_insert(ProcessedPayload)
        .values(source=source, poll_id=poll_id, raw_uri=raw_uri, finding_count=finding_count)
        .on_conflict_do_nothing(constraint="uq_processed_payloads_source_poll")
        .returning(ProcessedPayload.id)
    )
    result = session.execute(stmt).scalar()
    return result is not None


def _emit(
    session: Session,
    finding_id: UUID,
    event_type: EventType,
    from_value: str | None,
    to_value: str,
    actor: str,
) -> None:
    session.add(
        FindingEvent(
            finding_id=finding_id,
            event_type=event_type,
            from_value=from_value,
            to_value=to_value,
            actor=actor,
            occurred_at=_utcnow(),
        )
    )


def _diff_and_emit(
    session: Session, existing: Finding, incoming: NormalizedFinding, actor: str
) -> int:
    """Compare tracked fields, mutate `existing`, emit one event per change.

    Returns the number of events emitted (purely for logging / metrics).
    """
    events = 0
    if existing.severity != incoming.severity:
        _emit(
            session,
            existing.id,
            EventType.severity_changed,
            existing.severity.value,
            incoming.severity.value,
            actor,
        )
        existing.severity = incoming.severity
        events += 1

    if existing.title != incoming.title:
        _emit(session, existing.id, EventType.title_changed, existing.title, incoming.title, actor)
        existing.title = incoming.title
        events += 1

    if existing.description != incoming.description:
        _emit(
            session,
            existing.id,
            EventType.description_changed,
            existing.description[:512] or None,
            incoming.description[:512],
            actor,
        )
        existing.description = incoming.description
        events += 1
    return events


def process_snapshot(
    session: Session,
    *,
    source: str,
    poll_id: UUID,
    raw_uri: str,
    findings: Iterable[NormalizedFinding],
    owner_resolver: Callable[[str, str, list[str]], str],
    auto_close_threshold: int | None,
) -> SnapshotResult:
    """Apply the full snapshot to the DB. Caller must wrap in a session/transaction."""
    incoming = list(findings)
    actor = f"system:{source}_ingest"
    now = _utcnow()

    if not _record_processed(session, source, poll_id, raw_uri, len(incoming)):
        log.info("snapshot.already_processed", source=source, poll_id=str(poll_id))
        return SnapshotResult(True, 0, 0, 0, 0, 0, len(incoming))

    # A snapshot may produce findings under more than one logical source (today:
    # SonarCloud's poller emits both `sonarcloud` and `sonarcloud_trivy`). Both
    # sets must participate in absent-detection, auto-close, and the per-row
    # source re-stamp; otherwise a Trivy-in-Sonar finding that disappears from
    # a future snapshot would never age or auto-close, and a mapper-driven
    # reclassification of an existing row would not be applied.
    finding_sources = SOURCE_GROUPS.get(source, frozenset({source}))

    incoming_ids = [f.id for f in incoming]

    existing_by_id: dict[UUID, Finding] = {}
    if incoming_ids:
        existing_by_id = {
            f.id: f for f in session.scalars(select(Finding).where(Finding.id.in_(incoming_ids)))
        }

    # ----- Stale-id reconciliation -----
    # An earlier mapper deploy may have produced rows whose `Finding.id` was
    # derived from the *classified* source (e.g. uuid5("sonarcloud_trivy:" +
    # native_id)) before the SonarCloud Trivy split moved to a source-stable
    # id derivation (uuid5("sonarcloud:" + native_id)). Such a row matches an
    # incoming finding by (source, native_id) but not by id, and would
    # otherwise:
    #   (a) collide with the unique constraint `uq_findings_source_native_id`
    #       when the row at the source-stable id is re-stamped to the same
    #       (source, native_id) pair the stale row already occupies, or
    #   (b) leave a permanent orphan that the new mapper can no longer locate
    #       by id, so it ages and auto-closes while a fresh row is inserted.
    #
    # The reconciler runs once per snapshot, before the per-finding loop, and
    # for each stale row in the SOURCE_GROUPS set whose id differs from the
    # source-stable id the new mapper produces:
    #   - Scenario 2 (a sibling row already holds the source-stable id):
    #     migrate the stale row's events onto the sibling so the audit trail
    #     is preserved, then delete the duplicate. The sibling's source is
    #     re-stamped a few lines later by the existing-path branch.
    #   - Scenario 1 (no sibling — only the stale row exists): delete it
    #     unconditionally; the for-loop's insert path will create a fresh
    #     row at the source-stable id. The stale row's events are lost in
    #     this branch (the FK has no `ON UPDATE CASCADE` and is not
    #     declared `DEFERRABLE`, so we cannot re-key the row in place
    #     without dropping events first). This is acceptable because the
    #     reconciler only fires on the migration from a buggy older deploy
    #     and is a one-shot operation for the affected rows.
    #
    # The branch is a no-op once every row in `finding_sources` is on the
    # source-stable scheme; cost is one extra SELECT per snapshot.
    incoming_native_ids = list({f.native_id for f in incoming})
    incoming_by_source_native = {(f.source, f.native_id): f for f in incoming}
    if incoming_native_ids:
        candidates = list(
            session.scalars(
                select(Finding).where(
                    Finding.source.in_(finding_sources),
                    Finding.native_id.in_(incoming_native_ids),
                )
            )
        )
        for stale in candidates:
            if stale.id in existing_by_id:
                continue  # already at the source-stable id; nothing to migrate
            nf_match = incoming_by_source_native.get((stale.source, stale.native_id))
            if nf_match is None or stale.id == nf_match.id:
                continue
            keeper = existing_by_id.get(nf_match.id)
            if keeper is not None:
                # Scenario 2: re-parent the stale row's events onto the
                # keeper. The SQL update bypasses the ORM relationship cache,
                # which is fine because we never loaded `stale.events` —
                # SQLAlchemy will re-query when (if) cascade fires below and
                # find zero rows.
                session.execute(
                    update(FindingEvent)
                    .where(FindingEvent.finding_id == stale.id)
                    .values(finding_id=keeper.id)
                )
                session.flush()
            log.info(
                "snapshot.reconciled_stale_finding",
                source=stale.source,
                native_id=stale.native_id,
                stale_id=str(stale.id),
                target_id=str(nf_match.id),
                merged=keeper is not None,
            )
            session.delete(stale)
            session.flush()

    inserted = updated = reopened = 0

    for nf in incoming:
        existing = existing_by_id.get(nf.id)
        owner_team = (
            nf.owner_team
            if nf.owner_team is not None
            else owner_resolver(nf.source, nf.asset_id, nf.tags)
        )

        if existing is None:
            session.add(
                Finding(
                    id=nf.id,
                    source=nf.source,
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
                    owner_team=owner_team,
                    correlation_group_id=nf.correlation_group_id,
                    status=Status.open,
                    first_seen_at=now,
                    last_seen_at=now,
                    upstream_created_at=nf.upstream_created_at,
                    consecutive_misses=0,
                    raw_payload_uri=raw_uri,
                    tags=nf.tags,
                    wiz_category=nf.wiz_category,
                    upstream_url=nf.upstream_url,
                )
            )
            session.flush()  # ensure the FK target exists for the event
            _emit(session, nf.id, EventType.discovered, None, Status.open.value, actor)
            inserted += 1
            continue

        if existing.status == Status.auto_closed:
            _emit(
                session,
                existing.id,
                EventType.reopened,
                existing.status.value,
                Status.open.value,
                actor,
            )
            existing.status = Status.open
            existing.consecutive_misses = 0
            # Restart the SLA clock — a re-introduced vulnerability gets a fresh
            # window. Read by `Finding.sla_started_at`.
            existing.reopened_at = now
            reopened += 1

        events = _diff_and_emit(session, existing, nf, actor)

        # Re-stamp `Finding.source` from the incoming mapping when a poller
        # produces multiple logical sources (today: SonarCloud emits both
        # `sonarcloud` and `sonarcloud_trivy`) and the mapper's
        # classification has changed for an existing row. Without this, a
        # mapper improvement (e.g., learning a new Trivy detection signal)
        # would only take effect for *newly inserted* findings; pre-existing
        # rows with the old classification would stay misclassified until
        # they auto-closed and a fresh row was inserted N polls later, which
        # leaks the misclassified rows into /developer for the duration of
        # that window. We restrict the re-stamp to within a known
        # SOURCE_GROUPS set so a buggy mapper can't accidentally flip
        # cross-poller (a dependabot finding becoming a sonarcloud one is a
        # bug, not a reclassification).
        if nf.source != existing.source and nf.source in finding_sources:
            existing.source = nf.source
        # Re-stamp the asset fields so mapper-driven canonicalization
        # propagates to pre-existing rows. Two scenarios this is load-bearing
        # for:
        #
        #   1. An `assets[*].sonar_project_key` override added retroactively
        #      to ownership.yaml — the resolved asset_id flips from the
        #      convention path (`repo:{github_org}/{repo}`) to the override
        #      target (e.g. `sonarproj:<key>`).
        #   2. A GITHUB_ORG env-var fix that changes the resolved repo
        #      casing — historical Sonar rows persisted while GITHUB_ORG was
        #      empty kept the lowercase organization fallback (e.g.
        #      `repo:exampleorg/example-service`) even after the env var was set
        #      back to the canonical `ExampleOrg`. Without this re-stamp those
        #      rows never converge: `OwnershipMap.team_for_asset` is a
        #      case-sensitive dict lookup against `ownership.yaml.assets[*].id`,
        #      so the lowercase asset_id reads back as `unowned`, and the
        # nightly rollup belt-and-braces `core_reresolve`
        #      flips the row from its correct team back to `unowned` on the
        #      stored value, undoing any healing the mapper just did at
        #      ingest. The fix is to persist the canonicalized asset_id so
        #      both ingest-time and re-resolve-time lookups agree.
        #
        # No event is emitted — same contract as the `source` re-stamp above:
        # this is a storage canonicalization, not a domain transition.
        # `owner_team` is resolved a few lines up against `nf.asset_id` (the
        # new value), so the persisted asset_id and owner_team end up in
        # lockstep after this block.
        existing.asset_id = nf.asset_id
        existing.asset_type = nf.asset_type
        existing.asset_root = nf.asset_root
        existing.asset_display = nf.asset_display
        if existing.owner_team != owner_team:
            _emit(
                session,
                existing.id,
                EventType.ownership_changed,
                existing.owner_team,
                owner_team,
                actor,
            )
            existing.owner_team = owner_team
        existing.correlation_group_id = nf.correlation_group_id
        existing.tags = nf.tags
        existing.raw_payload_uri = raw_uri
        existing.last_seen_at = now
        existing.consecutive_misses = 0
        # Trust the source: upstream creation timestamps are immutable, so always
        # re-stamp from the snapshot. This also backfills NULL values left over
        # from migration ad807828ff66.
        if nf.upstream_created_at is not None:
            existing.upstream_created_at = nf.upstream_created_at
        if nf.wiz_category is not None:
            existing.wiz_category = nf.wiz_category
        if nf.upstream_url is not None:
            existing.upstream_url = nf.upstream_url

        if events > 0:
            updated += 1

    open_statuses = [s.value for s in Status.open_set()]

    absent_filter = [
        Finding.source.in_(finding_sources),
        Finding.status.in_(open_statuses),
    ]
    if incoming_ids:
        absent_filter.append(Finding.id.notin_(incoming_ids))

    absent_marked = (
        session.execute(
            update(Finding)
            .where(*absent_filter)
            .values(consecutive_misses=Finding.consecutive_misses + 1)
        ).rowcount
        or 0
    )

    auto_closed = 0
    if auto_close_threshold is not None:
        to_close = session.scalars(
            select(Finding).where(
                Finding.source.in_(finding_sources),
                Finding.status.in_(open_statuses),
                Finding.consecutive_misses >= auto_close_threshold,
            )
        ).all()
        for f in to_close:
            _emit(
                session,
                f.id,
                EventType.auto_closed,
                f.status.value,
                Status.auto_closed.value,
                "system:auto_close",
            )
            f.status = Status.auto_closed
            auto_closed += 1

    log.info(
        "snapshot.processed",
        source=source,
        poll_id=str(poll_id),
        finding_count=len(incoming),
        inserted=inserted,
        updated=updated,
        reopened=reopened,
        absent_marked=absent_marked,
        auto_closed=auto_closed,
    )

    return SnapshotResult(
        already_processed=False,
        inserted=inserted,
        updated=updated,
        reopened=reopened,
        auto_closed=auto_closed,
        absent_marked=absent_marked,
        finding_count=len(incoming),
    )
