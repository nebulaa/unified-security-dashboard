"""`GET /metrics/coverage` — cloud security coverage for the executive view."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import current_user
from app.core.rbac import UserContext
from app.coverage.compute import build_report
from app.coverage.config import get_coverage_config
from app.coverage.model import CoverageReport, Ratio
from app.coverage.store import SnapshotNotFoundError, load_latest

log = logging.getLogger("secdb.api.coverage")

router = APIRouter(prefix="/metrics", tags=["metrics"])


class CoverageRatioResponse(BaseModel):
    covered: int
    in_scope: int
    excepted: int
    gaps: int
    pct: float | None


class CoverageSecondaryResponse(BaseModel):
    key: str
    label: str
    unit: str
    ratio: CoverageRatioResponse


class CoverageMetricResponse(BaseModel):
    key: str
    label: str
    definition: str
    unit: str
    ratio: CoverageRatioResponse
    rag: str
    delta_pts: float | None
    trend: list[float]
    gap_items: list[str]
    unavailable_sources: list[str]
    secondary: CoverageSecondaryResponse | None


class CoverageLayerResponse(BaseModel):
    key: str
    label: str
    scope: str
    metrics: list[CoverageMetricResponse]


class CoverageProjectCellResponse(BaseModel):
    metric: str
    label: str
    ratio: CoverageRatioResponse
    rag: str
    note: str
    unavailable_sources: list[str]


class CoverageProjectResponse(BaseModel):
    key: str
    label: str
    flagship: bool
    cells: list[CoverageProjectCellResponse]


class CoverageUnmappedResponse(BaseModel):
    repos: int
    cloud_accounts: int


class CoverageResponse(BaseModel):
    as_of: datetime
    collection_mode: str
    stale: bool
    green_pct: float
    amber_pct: float
    layers: list[CoverageLayerResponse]
    projects: list[CoverageProjectResponse]
    unmapped: CoverageUnmappedResponse
    degraded_sources: list[str]


def _ratio(ratio: Ratio) -> CoverageRatioResponse:
    return CoverageRatioResponse(
        covered=ratio.covered,
        in_scope=ratio.in_scope,
        excepted=ratio.excepted,
        gaps=ratio.gaps,
        pct=ratio.pct,
    )


def _to_response(report: CoverageReport) -> CoverageResponse:
    return CoverageResponse(
        as_of=report.as_of,
        collection_mode=report.collection_mode,
        stale=report.stale,
        green_pct=report.green_pct,
        amber_pct=report.amber_pct,
        layers=[
            CoverageLayerResponse(
                key=layer.key,
                label=layer.label,
                scope=layer.scope,
                metrics=[
                    CoverageMetricResponse(
                        key=metric.key,
                        label=metric.label,
                        definition=metric.definition,
                        unit=metric.unit,
                        ratio=_ratio(metric.ratio),
                        rag=metric.rag,
                        delta_pts=metric.delta_pts,
                        trend=list(metric.trend),
                        gap_items=list(metric.gap_items),
                        unavailable_sources=list(metric.unavailable_sources),
                        secondary=(
                            CoverageSecondaryResponse(
                                key=metric.secondary.key,
                                label=metric.secondary.label,
                                unit=metric.secondary.unit,
                                ratio=_ratio(metric.secondary.ratio),
                            )
                            if metric.secondary
                            else None
                        ),
                    )
                    for metric in layer.metrics
                ],
            )
            for layer in report.layers
        ],
        projects=[
            CoverageProjectResponse(
                key=project.key,
                label=project.label,
                flagship=project.flagship,
                cells=[
                    CoverageProjectCellResponse(
                        metric=cell.metric,
                        label=cell.label,
                        ratio=_ratio(cell.ratio),
                        rag=cell.rag,
                        note=cell.note,
                        unavailable_sources=list(cell.unavailable_sources),
                    )
                    for cell in project.cells
                ],
            )
            for project in report.projects
        ],
        unmapped=CoverageUnmappedResponse(
            repos=report.unmapped.repos,
            cloud_accounts=report.unmapped.cloud_accounts,
        ),
        degraded_sources=list(report.degraded_sources),
    )


@router.get("/coverage", response_model=CoverageResponse)
def get_coverage(
    _user: Annotated[UserContext, Depends(current_user)],
) -> CoverageResponse:
    try:
        snapshot = load_latest()
    except SnapshotNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return _to_response(build_report(snapshot, get_coverage_config()))
