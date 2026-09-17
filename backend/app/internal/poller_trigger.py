"""Start Dependabot / SonarCloud pollers from the admin API."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings, get_settings
from app.internal.cloud_run_jobs import run_cloud_run_job

log = logging.getLogger("secdb.poller_trigger")

PollerSource = Literal["dependabot", "sonarcloud", "wiz", "pentest"]

POLLER_SOURCES: frozenset[PollerSource] = frozenset({"dependabot", "sonarcloud", "wiz", "pentest"})


@dataclass(frozen=True)
class PollerRunResult:
    source: PollerSource
    mode: Literal["cloud_run", "local"]
    job_name: str | None
    execution_name: str | None
    message: str


def _job_name_for(source: PollerSource, settings: Settings) -> str:
    if source == "dependabot":
        return settings.poller_job_dependabot
    if source == "sonarcloud":
        return settings.poller_job_sonarcloud
    if source == "pentest":
        return settings.poller_job_jira_pentest
    return settings.poller_job_wiz


def _uses_cloud_run(settings: Settings) -> bool:
    return bool(
        settings.ingest_transport == "pubsub"
        and settings.pubsub_project
        and settings.gcp_region
    )


def _run_local_poller(source: PollerSource) -> int:
    if source == "dependabot":
        from app.pollers.dependabot import run

        return run()
    if source == "sonarcloud":
        from app.pollers.sonarcloud import run

        return run()
    if source == "pentest":
        from app.pollers.jira_pentest import run

        return run()
    from app.pollers.wiz import run

    return run()


def trigger_poller(source: PollerSource, settings: Settings | None = None) -> PollerRunResult:
    """Start a poller. Cloud Run Job in GCP; background thread when local."""
    if source not in POLLER_SOURCES:
        raise ValueError(f"unknown poller source: {source}")

    s = settings or get_settings()
    if _uses_cloud_run(s):
        if not s.pubsub_project or not s.gcp_region:
            raise RuntimeError("poller trigger requires PUBSUB_PROJECT and GCP_REGION")
        job_name = _job_name_for(source, s)
        execution = run_cloud_run_job(
            project=s.pubsub_project,
            region=s.gcp_region,
            job_name=job_name,
        )
        return PollerRunResult(
            source=source,
            mode="cloud_run",
            job_name=job_name,
            execution_name=execution,
            message=f"Cloud Run Job {job_name} started",
        )

    def _background() -> None:
        try:
            code = _run_local_poller(source)
            if code != 0:
                log.error("poller.local_failed source=%s exit=%d", source, code)
        except Exception:
            log.exception("poller.local_failed source=%s", source)

    threading.Thread(target=_background, daemon=True, name=f"poller-{source}").start()
    return PollerRunResult(
        source=source,
        mode="local",
        job_name=None,
        execution_name=None,
        message=f"Local poller {source} started in background",
    )
