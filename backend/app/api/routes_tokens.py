"""`POST/GET/DELETE /me/tokens` — self-service personal API tokens.

Only browser sessions (IAP or dev identity) may mint or revoke tokens. Bearer-
authenticated requests are rejected to prevent token recursion.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session
from app.core.config import get_settings
from app.core.identity import require_browser_session
from app.core.models import ApiToken
from app.core.rbac import UserContext
from app.core.tokens import generate_token

log = logging.getLogger("secdb.tokens")

router = APIRouter(tags=["tokens"])

MAX_ACTIVE_TOKENS_PER_USER = 5


class CreateTokenRequest(BaseModel):
    label: str | None = Field(default=None, max_length=64)
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Omitted = no expiry.",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Explicit expiry (ISO datetime). Overrides expires_in_days when set.",
    )


class TokenCreatedResponse(BaseModel):
    id: UUID
    label: str | None
    prefix: str
    expires_at: datetime | None
    created_at: datetime
    token: str


class TokenSummary(BaseModel):
    id: UUID
    label: str | None
    prefix: str
    expires_at: datetime | None
    created_at: datetime
    last_used_at: datetime | None


class TokenListResponse(BaseModel):
    items: list[TokenSummary]
    max_active: int = MAX_ACTIVE_TOKENS_PER_USER


class McpConfigResponse(BaseModel):
    mcp_server_url: str


def _active_count(session: Session, email: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(ApiToken)
            .where(ApiToken.email == email, ApiToken.revoked_at.is_(None))
        )
        or 0
    )


def _resolve_expires(
    expires_in_days: int | None, expires_at: datetime | None
) -> datetime | None:
    if expires_at is not None:
        if expires_at.tzinfo is None:
            return expires_at.replace(tzinfo=UTC)
        return expires_at
    if expires_in_days is None:
        return None
    return datetime.now(UTC) + timedelta(days=expires_in_days)


@router.get("/me/mcp-config", response_model=McpConfigResponse)
def mcp_config(
    user: Annotated[UserContext, Depends(current_user)],
) -> McpConfigResponse:
    """Public MCP server URL for setup snippets on /settings/mcp."""
    _ = user
    return McpConfigResponse(mcp_server_url=get_settings().mcp_server_url)


@router.post("/me/tokens", response_model=TokenCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_token(
    body: CreateTokenRequest,
    request: Request,
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
) -> TokenCreatedResponse:
    require_browser_session(request)

    if _active_count(session, user.email) >= MAX_ACTIVE_TOKENS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"maximum of {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached; revoke one first",
        )

    plaintext, digest, prefix = generate_token()
    expires = _resolve_expires(body.expires_in_days, body.expires_at)
    now = datetime.now(UTC)

    # `active_role` column is a legacy holdover from the old four-role model
    #. It no longer gates anything — the bearer token simply
    # inherits the owner's per-email admin status at verify time. Hardcoded
    # to "member" so the NOT NULL constraint stays satisfied without a
    # schema migration.
    row = ApiToken(
        email=user.email,
        token_hash=digest,
        prefix=prefix,
        label=body.label,
        active_role="member",
        expires_at=expires,
        created_at=now,
    )
    session.add(row)
    session.flush()

    log.info(
        "api_token.issued actor=%s token_id=%s expires_at=%s",
        user.email,
        str(row.id),
        expires.isoformat() if expires else None,
    )

    return TokenCreatedResponse(
        id=row.id,
        label=row.label,
        prefix=row.prefix,
        expires_at=row.expires_at,
        created_at=row.created_at,
        token=plaintext,
    )


@router.get("/me/tokens", response_model=TokenListResponse)
def list_tokens(
    request: Request,
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
) -> TokenListResponse:
    require_browser_session(request)

    rows = list(
        session.scalars(
            select(ApiToken)
            .where(ApiToken.email == user.email, ApiToken.revoked_at.is_(None))
            .order_by(ApiToken.created_at.desc())
        )
    )
    return TokenListResponse(
        items=[
            TokenSummary(
                id=r.id,
                label=r.label,
                prefix=r.prefix,
                expires_at=r.expires_at,
                created_at=r.created_at,
                last_used_at=r.last_used_at,
            )
            for r in rows
        ],
    )


@router.delete("/me/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: UUID,
    request: Request,
    user: Annotated[UserContext, Depends(current_user)],
    session: Annotated[Session, Depends(db_session)],
) -> None:
    require_browser_session(request)

    row = session.scalar(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.email == user.email,
            ApiToken.revoked_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="token not found")

    row.revoked_at = datetime.now(UTC)
    log.info("api_token.revoked actor=%s token_id=%s", user.email, str(token_id))
