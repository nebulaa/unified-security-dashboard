"""`GET /components` — Component Registry for view SSR."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import current_user
from app.core.config_store import get_config_cache
from app.core.rbac import UserContext

router = APIRouter()


class ComponentRowResponse(BaseModel):
    key: str
    label: str
    application: str
    application_label: str
    repo: str | None
    sonar_projects: list[str]
    teams: list[str]
    views: list[str]
    dev_pillar: str | None
    wiz_service: str | None


class ExecutiveSubTeamResponse(BaseModel):
    label: str
    team_key: str | None


class ExecutivePillarResponse(BaseModel):
    key: str
    label: str
    team_keys: list[str]
    sub_teams: list[ExecutiveSubTeamResponse]


class ApplicationResponse(BaseModel):
    key: str
    label: str
    services: list[str]
    repos: list[str]
    teams: list[str]
    dev_pillar: str | None


class DeveloperScopeResponse(BaseModel):
    team_keys: list[str]


class ComponentRegistryIndexes(BaseModel):
    wiz_service_to_team: dict[str, str]
    wiz_teams_for_pillar: dict[str, list[str]]


class ComponentRegistryResponse(BaseModel):
    version: int
    loaded_at: float
    components: list[ComponentRowResponse]
    executive_pillars: list[ExecutivePillarResponse]
    applications: list[ApplicationResponse]
    developer_scope: DeveloperScopeResponse
    indexes: ComponentRegistryIndexes


@router.get("/components", response_model=ComponentRegistryResponse)
def get_components(
    _user: Annotated[UserContext, Depends(current_user)],
) -> ComponentRegistryResponse:
    reg = get_config_cache().get_component_registry()
    return ComponentRegistryResponse(
        version=reg.version,
        loaded_at=reg.loaded_at,
        components=[
            ComponentRowResponse(
                key=c.key,
                label=c.label,
                application=c.application,
                application_label=c.application_label,
                repo=c.repo,
                sonar_projects=list(c.sonar_projects),
                teams=list(c.teams),
                views=sorted(c.views),
                dev_pillar=c.dev_pillar,
                wiz_service=c.wiz_service,
            )
            for c in reg.components
        ],
        executive_pillars=[
            ExecutivePillarResponse(
                key=p.key,
                label=p.label,
                team_keys=list(p.team_keys),
                sub_teams=[
                    ExecutiveSubTeamResponse(label=s.label, team_key=s.team_key)
                    for s in p.sub_teams
                ],
            )
            for p in reg.executive_pillars
        ],
        applications=[
            ApplicationResponse(
                key=a.key,
                label=a.label,
                services=list(a.services),
                repos=list(a.repos),
                teams=list(a.teams),
                dev_pillar=a.dev_pillar,
            )
            for a in reg.applications
        ],
        developer_scope=DeveloperScopeResponse(
            team_keys=list(reg.developer_scope_team_keys),
        ),
        indexes=ComponentRegistryIndexes(
            wiz_service_to_team=dict(reg.wiz_service_to_team),
            wiz_teams_for_pillar={
                pillar: sorted(teams) for pillar, teams in reg.wiz_teams_for_pillar.items()
            },
        ),
    )
