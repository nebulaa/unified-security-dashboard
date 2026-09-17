"""Admin ownership re-resolution endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import db_session
from app.api.routes_admin_dlq import require_admin
from app.core.config import get_settings
from app.core.enums import EventType
from app.core.models import Finding, FindingEvent
from app.core.rbac import UserContext
from app.internal.ownership_trigger import trigger_ownership_reresolve

router = APIRouter(prefix="/admin/ownership", tags=["admin"])


class TeamCount(BaseModel):
    team: str
    count: int


class RecentOwnershipEvent(BaseModel):
    occurred_at: datetime
    from_team: str | None
    to_team: str
    actor: str


class OwnershipStatusResponse(BaseModel):
    owner_team_counts: list[TeamCount]
    unowned_count: int
    excluded_count: int
    ownership_changed_7d: int
    recent_events: list[RecentOwnershipEvent]
    trigger_mode: str


class OwnershipReresolveResponse(BaseModel):
    mode: str
    job_name: str | None
    execution_name: str | None
    rollup_execution_name: str | None
    message: str
    scanned: int | None = None
    updated: int | None = None
    by_transition: dict[str, int] | None = None
    rollup_triggered: bool | None = None


@router.get("", response_model=OwnershipStatusResponse)
def ownership_status(
    _user: Annotated[UserContext, Depends(require_admin)],
    session: Annotated[Session, Depends(db_session)],
) -> OwnershipStatusResponse:
    settings = get_settings()
    mode = (
        "cloud_run"
        if settings.ingest_transport == "pubsub" and settings.gcp_region
        else "local"
    )

    dist_rows = session.execute(
        select(Finding.owner_team, func.count())
        .group_by(Finding.owner_team)
        .order_by(func.count().desc())
    ).all()
    counts = [TeamCount(team=t, count=int(c)) for t, c in dist_rows]
    unowned = next((c for t, c in dist_rows if t == "unowned"), 0)
    excluded = next((c for t, c in dist_rows if t == "excluded"), 0)

    since = datetime.now(UTC) - timedelta(days=7)
    changed_7d = int(
        session.execute(
            select(func.count())
            .select_from(FindingEvent)
            .where(
                FindingEvent.event_type == EventType.ownership_changed,
                FindingEvent.occurred_at >= since,
            )
        ).scalar_one()
        or 0
    )

    recent_rows = session.execute(
        select(
            FindingEvent.occurred_at,
            FindingEvent.from_value,
            FindingEvent.to_value,
            FindingEvent.actor,
        )
        .where(FindingEvent.event_type == EventType.ownership_changed)
        .order_by(FindingEvent.occurred_at.desc())
        .limit(20)
    ).all()

    return OwnershipStatusResponse(
        owner_team_counts=counts[:40],
        unowned_count=int(unowned),
        excluded_count=int(excluded),
        ownership_changed_7d=changed_7d,
        recent_events=[
            RecentOwnershipEvent(
                occurred_at=occurred_at,
                from_team=from_v,
                to_team=to_v,
                actor=actor,
            )
            for occurred_at, from_v, to_v, actor in recent_rows
        ],
        trigger_mode=mode,
    )


@router.post("/reresolve", response_model=OwnershipReresolveResponse)
def ownership_reresolve(
    _user: Annotated[UserContext, Depends(require_admin)],
) -> OwnershipReresolveResponse:
    try:
        run = trigger_ownership_reresolve()
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"failed to start ownership re-resolve: {exc}",
        ) from exc

    payload: dict[str, Any] = {
        "mode": run.mode,
        "job_name": run.job_name,
        "execution_name": run.execution_name,
        "rollup_execution_name": run.rollup_execution_name,
        "message": run.message,
    }
    if run.result:
        payload["scanned"] = run.result.get("scanned")
        payload["updated"] = run.result.get("updated")
        payload["by_transition"] = run.result.get("by_transition")
        payload["rollup_triggered"] = run.result.get("rollup_triggered")
    return OwnershipReresolveResponse(**payload)
