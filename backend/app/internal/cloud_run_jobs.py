"""Trigger Cloud Run v2 Jobs (admin poller runs in GCP)."""

from __future__ import annotations

import logging

import google.auth
import google.auth.transport.requests
import httpx

log = logging.getLogger("secdb.cloud_run_jobs")

_RUN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def run_cloud_run_job(
    *,
    project: str,
    region: str,
    job_name: str,
    args: list[str] | None = None,
) -> str:
    """Start a job execution; return the execution resource name.

    When `args` is set, replaces the job template container args (e.g.
    ``["-m", "app.jobs.rollup", "--backfill-days", "30"]``).
    """
    credentials, _ = google.auth.default(scopes=[_RUN_SCOPE])
    credentials.refresh(google.auth.transport.requests.Request())
    if not credentials.token:
        raise RuntimeError("cloud_run_jobs: failed to obtain GCP credentials")

    url = (
        f"https://{region}-run.googleapis.com/v2/"
        f"projects/{project}/locations/{region}/jobs/{job_name}:run"
    )
    body: dict = {}
    if args:
        body["overrides"] = {"containerOverrides": [{"args": args}]}
    response = httpx.post(
        url,
        headers={"Authorization": f"Bearer {credentials.token}"},
        json=body,
        timeout=60.0,
    )
    if response.status_code >= 400:
        log.error(
            "cloud_run_jobs.run_failed job=%s status=%s body=%s",
            job_name,
            response.status_code,
            response.text[:500],
        )
        response.raise_for_status()

    body = response.json()
    execution = body.get("name")
    if not isinstance(execution, str) or not execution:
        raise RuntimeError(f"cloud_run_jobs: unexpected run response: {body!r}")
    log.info("cloud_run_jobs.started job=%s execution=%s", job_name, execution)
    return execution
