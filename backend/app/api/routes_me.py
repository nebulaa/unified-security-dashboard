"""`GET /me` — caller email + admin flag.

The full RBAC collapse means there is nothing else worth
returning: roles / teams_by_role / active_role / default_role were all built
to support the four-role hierarchy that no longer exists.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_user
from app.core.rbac import UserContext

router = APIRouter()


class MeResponse(BaseModel):
    email: str
    name: str
    is_admin: bool


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[UserContext, Depends(current_user)]) -> MeResponse:
    return MeResponse(email=user.email, name=user.name, is_admin=user.is_admin)
