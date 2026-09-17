"""`GET /teams` — read-only directory of teams from `ownership.yaml`.

Used by the UI to populate the team filter dropdown so we don't hardcode 23 names
in TypeScript. Returns a flat list sorted by `(pillar, display_name)` so the UI can
either render groups by pillar later or just use it as-is.

Auth: any authenticated user. Team identifiers are not sensitive — they're already
visible via `/findings` rows and `/me`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_user
from app.core.config_store import get_config_cache
from app.core.rbac import UserContext

router = APIRouter()


class TeamItem(BaseModel):
    name: str  # canonical key (use this when filtering)
    display_name: str | None
    pillar: str | None
    pillar_name: str | None  # human label of the pillar, if defined
    jira_project: str | None
    slack: str | None
    engineering_manager_name: str | None
    engineering_manager_email: str | None
    security_poc_name: str | None
    security_poc_email: str | None


class TeamListResponse(BaseModel):
    items: list[TeamItem]


@router.get("/teams", response_model=TeamListResponse)
def list_teams(
    _user: Annotated[UserContext, Depends(current_user)],
) -> TeamListResponse:
    om = get_config_cache().get_ownership()
    items = [
        TeamItem(
            name=t.name,
            display_name=t.display_name,
            pillar=t.pillar,
            pillar_name=om.pillars[t.pillar].name if t.pillar in om.pillars else None,
            jira_project=t.jira_project,
            slack=t.slack,
            engineering_manager_name=t.engineering_manager.name if t.engineering_manager else None,
            engineering_manager_email=t.engineering_manager.email if t.engineering_manager else None,
            security_poc_name=t.security_poc.name if t.security_poc else None,
            security_poc_email=t.security_poc.email if t.security_poc else None,
        )
        for t in om.teams.values()
    ]
    # Sort by pillar then display name (None goes last). The UI relies on this ordering.
    items.sort(
        key=lambda i: (
            i.pillar or "\uffff",
            (i.display_name or i.name).lower(),
        )
    )
    return TeamListResponse(items=items)
