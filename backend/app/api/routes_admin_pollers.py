"""Admin poller trigger endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.routes_admin_dlq import require_admin
from app.core.config import get_settings
from app.core.rbac import UserContext
from app.internal.poller_trigger import POLLER_SOURCES, PollerRunResult, trigger_poller

router = APIRouter(prefix="/admin/pollers", tags=["admin"])

PollerSourceParam = Literal["dependabot", "sonarcloud", "wiz", "pentest"]


class PollerInfo(BaseModel):
    source: PollerSourceParam
    job_name: str | None
    trigger_mode: Literal["cloud_run", "local"]


class PollerListResponse(BaseModel):
    items: list[PollerInfo]
    slack_configured: bool


class PollerRunResponse(BaseModel):
    source: PollerSourceParam
    mode: Literal["cloud_run", "local"]
    job_name: str | None
    execution_name: str | None
    message: str


def _to_response(result: PollerRunResult) -> PollerRunResponse:
    return PollerRunResponse(
        source=result.source,
        mode=result.mode,
        job_name=result.job_name,
        execution_name=result.execution_name,
        message=result.message,
    )


@router.get("", response_model=PollerListResponse)
def list_pollers(
    _user: Annotated[UserContext, Depends(require_admin)],
) -> PollerListResponse:
    settings = get_settings()
    mode: Literal["cloud_run", "local"] = (
        "cloud_run" if settings.ingest_transport == "pubsub" and settings.gcp_region else "local"
    )
    from app.internal.slack import resolve_slack_webhook_url

    items = [
        PollerInfo(
            source="dependabot",
            job_name=settings.poller_job_dependabot if mode == "cloud_run" else None,
            trigger_mode=mode,
        ),
        PollerInfo(
            source="sonarcloud",
            job_name=settings.poller_job_sonarcloud if mode == "cloud_run" else None,
            trigger_mode=mode,
        ),
        PollerInfo(
            source="wiz",
            job_name=settings.poller_job_wiz if mode == "cloud_run" else None,
            trigger_mode=mode,
        ),
        PollerInfo(
            source="pentest",
            job_name=settings.poller_job_jira_pentest if mode == "cloud_run" else None,
            trigger_mode=mode,
        ),
    ]
    return PollerListResponse(
        items=items,
        slack_configured=resolve_slack_webhook_url(settings) is not None,
    )


@router.post("/{source}/run", response_model=PollerRunResponse)
def run_poller(
    source: PollerSourceParam,
    _user: Annotated[UserContext, Depends(require_admin)],
) -> PollerRunResponse:
    if source not in POLLER_SOURCES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown poller: {source}")
    try:
        result = trigger_poller(source)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"failed to start poller: {exc}",
        ) from exc
    return _to_response(result)
