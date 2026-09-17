"""Admin DLQ triage endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.models import DlqEvent
from app.core.rbac import UserContext

router = APIRouter(prefix="/admin/dlq", tags=["admin"])


def require_admin(user: Annotated[UserContext, Depends(current_user)]) -> UserContext:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


class DlqEventItem(BaseModel):
    id: int
    message_id: str
    source: str | None
    poll_id: str | None
    raw_uri: str | None
    failure_reason: str | None
    delivery_attempt: int
    received_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None


class DlqListResponse(BaseModel):
    items: list[DlqEventItem]
    unresolved_count: int


@router.get("", response_model=DlqListResponse)
def list_dlq_events(
    user: Annotated[UserContext, Depends(require_admin)],
    session: Annotated[Session, Depends(db_session)],
    unresolved_only: bool = True,
    limit: int = 50,
) -> DlqListResponse:
    q = select(DlqEvent).order_by(DlqEvent.received_at.desc()).limit(min(limit, 200))
    if unresolved_only:
        q = q.where(DlqEvent.resolved_at.is_(None))

    rows = session.execute(q).scalars().all()
    unresolved_count = int(
        session.execute(
            select(func.count()).select_from(DlqEvent).where(DlqEvent.resolved_at.is_(None))
        ).scalar_one()
        or 0
    )

    return DlqListResponse(
        items=[
            DlqEventItem(
                id=r.id,
                message_id=r.message_id,
                source=r.source,
                poll_id=str(r.poll_id) if r.poll_id else None,
                raw_uri=r.raw_uri,
                failure_reason=r.failure_reason,
                delivery_attempt=r.delivery_attempt,
                received_at=r.received_at,
                resolved_at=r.resolved_at,
                resolved_by=r.resolved_by,
            )
            for r in rows
        ],
        unresolved_count=unresolved_count,
    )


@router.post("/{event_id}/resolve", response_model=DlqEventItem)
def resolve_dlq_event(
    event_id: int,
    user: Annotated[UserContext, Depends(require_admin)],
    session: Annotated[Session, Depends(db_session)],
) -> DlqEventItem:
    row = session.get(DlqEvent, event_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dlq event not found")
    if row.resolved_at is None:
        row.resolved_at = datetime.now(UTC)
        row.resolved_by = user.email
        session.add(row)
    return DlqEventItem(
        id=row.id,
        message_id=row.message_id,
        source=row.source,
        poll_id=str(row.poll_id) if row.poll_id else None,
        raw_uri=row.raw_uri,
        failure_reason=row.failure_reason,
        delivery_attempt=row.delivery_attempt,
        received_at=row.received_at,
        resolved_at=row.resolved_at,
        resolved_by=row.resolved_by,
    )
