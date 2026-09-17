"""`POST /feedback` — user feedback and inaccuracy reports routed to Slack."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.core.rbac import UserContext
from app.internal.slack import notify_user_feedback

router = APIRouter(tags=["feedback"])

FeedbackKind = Literal["feedback", "inaccuracy"]


class FeedbackRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    kind: FeedbackKind = "feedback"
    page_url: str | None = Field(default=None, max_length=2048)


class FeedbackResponse(BaseModel):
    sent: bool


@router.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackRequest,
    user: Annotated[UserContext, Depends(current_user)],
) -> FeedbackResponse:
    message = body.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="message is required",
        )
    sent = notify_user_feedback(
        kind=body.kind,
        message=message,
        email=user.email,
        name=user.name,
        page_url=(body.page_url or "").strip() or None,
    )
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="feedback channel is not configured",
        )
    return FeedbackResponse(sent=True)
