"""`GET /scanners/health` — last-seen per source vs expected cadence.

Cadence is hardcoded for the prototype (matches the Cloud Scheduler rates we'll set
up in Tier 1). `null` cadence means no scheduled poller — health is a no-op.

Status:
  active  : last seen within 1× expected cadence
  stale   : last seen between 1× and 3× expected cadence
  dark    : last seen >3× expected cadence
  no_data : never seen
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.api.schemas import ScannerHealth, ScannerHealthResponse
from app.core.models import ProcessedPayload
from app.core.rbac import UserContext

router = APIRouter(prefix="/scanners", tags=["scanners"])

EXPECTED_CADENCE_SECONDS: dict[str, int | None] = {
    "dependabot": 3_600,    # hourly
    "sonarcloud": 3_600,
    "trivy": 86_400,
    "wiz": 1_800,
    "nuclei": 86_400,
    "vanta": 86_400,
    "pentest": 3_600,
}


def _classify(now: datetime, last: datetime | None, cadence: int | None) -> str:
    if cadence is None:
        return "active" if last else "no_data"
    if last is None:
        return "no_data"
    age = (now - last).total_seconds()
    if age <= cadence:
        return "active"
    if age <= cadence * 3:
        return "stale"
    return "dark"


@router.get("/health", response_model=ScannerHealthResponse)
def scanner_health(
    _user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
) -> ScannerHealthResponse:
    now = datetime.now(UTC)
    rows = dict(
        session.execute(
            select(ProcessedPayload.source, func.max(ProcessedPayload.processed_at)).group_by(
                ProcessedPayload.source
            )
        ).all()
    )
    items: list[ScannerHealth] = []
    for source, cadence in EXPECTED_CADENCE_SECONDS.items():
        last = rows.get(source)
        items.append(
            ScannerHealth(
                source=source,
                last_seen_at=last,
                expected_cadence_seconds=cadence,
                status=_classify(now, last, cadence),
            )
        )
    active = sum(1 for i in items if i.status == "active")
    return ScannerHealthResponse(items=items, active=active, total=len(items))
