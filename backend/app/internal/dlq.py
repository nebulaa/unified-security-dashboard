"""Persist dead-letter ingest envelopes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.models import DlqEvent
from app.internal.pubsub import unwrap_pubsub_body


def _parse_snapshot_fields(payload: dict[str, Any]) -> tuple[str | None, UUID | None, str | None]:
    source = payload.get("source")
    poll_id_raw = payload.get("poll_id")
    raw_uri = payload.get("raw_uri")
    poll_id: UUID | None = None
    if poll_id_raw:
        try:
            poll_id = UUID(str(poll_id_raw))
        except ValueError:
            poll_id = None
    return (
        str(source) if source else None,
        poll_id,
        str(raw_uri) if raw_uri else None,
    )


def record_dlq_event(
    session: Session,
    *,
    message_id: str,
    envelope: dict[str, Any],
    delivery_attempt: int,
    failure_reason: str | None = None,
) -> bool:
    """Insert a DLQ row; return True if inserted, False if duplicate message_id."""
    inner: dict[str, Any] = envelope
    try:
        inner = unwrap_pubsub_body(envelope)
    except Exception:
        inner = {}

    source, poll_id, raw_uri = _parse_snapshot_fields(inner)

    stmt = (
        insert(DlqEvent)
        .values(
            message_id=message_id,
            source=source,
            poll_id=poll_id,
            raw_uri=raw_uri,
            envelope=envelope,
            failure_reason=failure_reason,
            delivery_attempt=delivery_attempt,
        )
        .on_conflict_do_nothing(index_elements=["message_id"])
        .returning(DlqEvent.id)
    )
    row = session.execute(stmt).first()
    return row is not None
