"""Trigger ownership re-resolution (admin / Makefile)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings, get_settings
from app.core.config_store import get_config_cache
from app.core.db import session_scope
from app.internal.cloud_run_jobs import run_cloud_run_job
from app.internal.ownership_reresolve import (
    core_reresolve,
    maybe_trigger_rollup_backfill,
    reresolve_result_to_dict,
)

log = logging.getLogger("secdb.ownership_trigger")


@dataclass
class OwnershipReresolveRunResult:
    mode: Literal["cloud_run", "local"]
    job_name: str | None
    execution_name: str | None
    rollup_execution_name: str | None
    message: str
    result: dict | None = None


def _uses_cloud_run(settings: Settings) -> bool:
    return bool(settings.ingest_transport == "pubsub" and settings.gcp_region and settings.pubsub_project)


def trigger_ownership_reresolve(settings: Settings | None = None) -> OwnershipReresolveRunResult:
    s = settings or get_settings()
    if _uses_cloud_run(s):
        job_name = s.ownership_reresolve_job
        execution = run_cloud_run_job(
            project=s.pubsub_project or "",
            region=s.gcp_region or "",
            job_name=job_name,
        )
        return OwnershipReresolveRunResult(
            mode="cloud_run",
            job_name=job_name,
            execution_name=execution,
            rollup_execution_name=None,
            message=(
                f"Cloud Run Job {job_name} started (re-resolve + 30d rollup backfill when updates occur). "
                "Check Cloud Run logs for per-team deltas."
            ),
        )

    ownership = get_config_cache().get_ownership()
    with session_scope() as session:
        rr = core_reresolve(session, ownership, actor="system:ownership_reresolve")
    rollup_triggered = maybe_trigger_rollup_backfill(rr.updated, async_mode=False)
    return OwnershipReresolveRunResult(
        mode="local",
        job_name=None,
        execution_name=None,
        rollup_execution_name=None,
        message=f"Re-resolved {rr.updated} of {rr.scanned} findings locally",
        result={**reresolve_result_to_dict(rr), "rollup_triggered": rollup_triggered},
    )
