"""SQLAlchemy models for findings, events, tokens, and related tables.

Identity contract:
    Finding.id = uuid5(NAMESPACE_SECDB, f"{source}:{native_id}")
    `(source, native_id)` is the unique business key; `id` is its deterministic projection.

Denormalizations on `findings`:
    - last_seen_at         updated unconditionally on every ingest, no event emitted
    - consecutive_misses   incremented per cycle when finding is absent; reset to 0 when present
    - owner_team           stamped at ingest from ownership.yaml; "unowned" if absent

Asset is inlined on `findings` for the prototype (single scanner, repos only). When a
second scanner is added that talks about a different asset_type for the same root (e.g.
a container image of a repo), we extract `assets` and link via FK in a follow-up
migration. `asset_root` is what `correlation_group_id` is computed against.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.enums import EventType, Severity, Status


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)
    native_id: Mapped[str] = mapped_column(String(512), nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity", native_enum=True), nullable=False
    )
    cve_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cwe_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    asset_id: Mapped[str] = mapped_column(String(512), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_root: Mapped[str] = mapped_column(String(512), nullable=False)
    asset_display: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    owner_team: Mapped[str] = mapped_column(String(128), nullable=False, default="unowned")

    correlation_group_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    status: Mapped[Status] = mapped_column(
        SAEnum(Status, name="status", native_enum=True), nullable=False, default=Status.open
    )

    # `first_seen_at` = first time *we* ingested this finding (kept for debugging /
    # ingest provenance). It is NOT a good age clock — see `sla_started_at` below.
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    # `upstream_created_at` = the source's own creation timestamp (GitHub's
    # `alert.created_at`, Sonar's `creationDate`, etc.). Set every ingest from the
    # mapper because upstream values are immutable; nullable for legacy rows where
    # the source didn't expose one. THIS is the canonical age anchor for SLA.
    upstream_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # `reopened_at` = wall clock at the most recent auto_closed -> open transition.
    # Kept for the event audit trail and for /admin to flag flappy findings; it
    # used to be the SLA anchor on the "re-introduced vulnerability gets a fresh
    # window" rationale but in practice the reopen path fires almost exclusively
    # after our own absent-detection bugs (e.g. the SonarCloud multi-org cross-
    # contamination in commit 8d11948 that bulk-auto-closed and then bulk-
    # reopened 1k+ valid findings within minutes of each other), which made
    # every old Sonar finding read as "3 hours old" on the live API. The
    # anchor now coalesces `upstream_created_at` -> `first_seen_at` only;
    # `reopened_at` no longer participates. See `app/api/sla.py` for the full
    # rationale.
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_misses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    raw_payload_uri: Mapped[str] = mapped_column(Text, nullable=False, default="")

    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)

    # Wiz detector type; NULL for non-Wiz findings.
    wiz_category: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Wiz portal deep link from GraphQL portalUrl when available.
    upstream_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=_utcnow
    )

    events: Mapped[list[FindingEvent]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="FindingEvent.occurred_at"
    )

    __table_args__ = (
        UniqueConstraint("source", "native_id", name="uq_findings_source_native_id"),
        Index("ix_findings_source_status", "source", "status"),
        Index("ix_findings_owner_team_status", "owner_team", "status"),
        Index("ix_findings_correlation_group", "correlation_group_id"),
        Index("ix_findings_asset_root", "asset_root"),
    )

    @property
    def is_open(self) -> bool:
        return self.status in Status.open_set()

    @property
    def is_closed(self) -> bool:
        return self.status in Status.closed_set()

    @property
    def sla_started_at(self) -> datetime:
        """Anchor for age + SLA. Precedence: upstream_created_at > first_seen_at.

        - A new finding ages from when the upstream source detected it.
        - Falls back to `first_seen_at` for legacy rows where the source timestamp
          was unavailable at ingest time.

        `reopened_at` is intentionally NOT in this precedence — see `app/api/sla.py`
        for the rationale (the auto_close + reopen lifecycle fires on dashboard-
        internal events, not on real source-side re-introductions, and using it
        as the anchor reset the age clock to "now" for 1k+ Sonar findings
        whenever the absent-detection logic glitched).
        """
        return self.upstream_created_at or self.first_seen_at


class FindingEvent(Base):
    """Append-only state-change log. — typed events only, no `re_seen`."""

    __tablename__ = "finding_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(
        SAEnum(EventType, name="event_type", native_enum=True), nullable=False
    )
    from_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_value: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    finding: Mapped[Finding] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_finding_events_finding_occurred", "finding_id", "occurred_at"),
        Index("ix_finding_events_type_occurred", "event_type", "occurred_at"),
    )


class ProcessedPayload(Base):
    """Idempotency table for the normalizer.

    Insert-on-conflict semantics: a redelivered Pub/Sub (or local HTTP) message that
    references an already-processed `(source, poll_id)` is acked without re-running the
    snapshot transaction.
    """

    __tablename__ = "processed_payloads"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    poll_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    raw_uri: Mapped[str] = mapped_column(Text, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    finding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("source", "poll_id", name="uq_processed_payloads_source_poll"),
        Index("ix_processed_payloads_source_processed", "source", "processed_at"),
    )


class RoleOverride(Base):
    """Manual role grantsTier B. One row per (email, role, team)."""

    __tablename__ = "role_overrides"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    team: Mapped[str | None] = mapped_column(String(128), nullable=True)
    granted_by: Mapped[str] = mapped_column(String(256), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("email", "role", "team", name="uq_role_overrides_email_role_team"),
        Index("ix_role_overrides_email", "email"),
    )


class ApiToken(Base):
    """Personal API tokens for MCP clients.

    `token_hash` stores SHA-256 hex of the full plaintext (`secdb_live_...`).
    `active_role` is snapshotted at issue time and enforced on every bearer
    request via live role re-derivation (403 if the user no longer holds it).
    """

    __tablename__ = "api_tokens"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active_role: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index(
            "ix_api_tokens_email_active",
            "email",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class RiskAccept(Base):
    """Pentest-only risk acceptance — design §7.4. Schema committed; not used in prototype."""

    __tablename__ = "risk_accepts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    finding_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    accepted_by: Mapped[str] = mapped_column(String(256), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (Index("ix_risk_accepts_finding", "finding_id"),)


class DailyMetric(Base):
    """Pre-aggregated rollup — design §7.3. Populated by nightly Job (Tier 1, deferred)."""

    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False)
    team: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity", native_enum=True, create_type=False), nullable=False
    )
    open_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fixed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_breached_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    median_age_days: Mapped[float] = mapped_column(nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint(
            "date", "team", "source", "severity", name="uq_daily_metrics_date_team_source_sev"
        ),
        Index("ix_daily_metrics_date_team", "date", "team"),
    )


class DlqEvent(Base):
    """Permanent ingest failure captured from the Pub/Sub dead-letter topic."""

    __tablename__ = "dlq_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    raw_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    envelope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("message_id", name="uq_dlq_events_message_id"),
        Index(
            "ix_dlq_events_unresolved",
            "received_at",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )


class AuditEvent(Base):
    """Audit log for admin operations (CLI grants/revokes, manual overrides, etc.)."""

    __tablename__ = "audit"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    actor: Mapped[str] = mapped_column(String(256), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_audit_actor_occurred", "actor", "occurred_at"),
        Index("ix_audit_action_occurred", "action", "occurred_at"),
    )
