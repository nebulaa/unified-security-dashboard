"""SonarCloud poller (Cloud Run Job in prod, plain CLI command locally).

Fetches `GET {SONAR_BASE_URL}/api/issues/search` filtered to vulnerabilities only and
to actionable statuses (open / confirmed / reopened). Pagination follows Sonar's
`paging.{pageIndex,pageSize,total}` shape; we walk pages until we've seen `total`
issues or hit the documented 10k cap (Sonar's hard limit on paginated reads).

Hotspots are NOT ingested in v1. They use
a different lifecycle and would need a separate `/api/hotspots/search` flow plus a
distinct status mapping; revisit when we're ready to surface them in the UI.

Locally:
    make poller-sonarcloud
    # or:
    python -m app.pollers.sonarcloud
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any
from uuid import uuid4

import httpx

from app.adapters.ingest_transport import build_ingest_transport
from app.adapters.raw_store import build_raw_store
from app.adapters.secrets import SecretRef, build_secret_backend
from app.core.config import get_settings

log = logging.getLogger("secdb.pollers.sonarcloud")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

PAGE_SIZE = 500  # Sonar caps individual page size at 500
HARD_PAGE_CAP = 20  # 20 * 500 = 10k issues, Sonar's documented total cap
SONAR_SOURCE_NAME = "sonarcloud"

# Fields the mapper (`app.normalizer.mappers.sonarcloud`) actually reads.
# Sonar's `/api/issues/search` also returns `flows` (taint-analysis path graphs),
# clean-code attributes, debt/effort, impacts, etc. — unused by us, but a single
# `cpp:S5145` issue can carry ~600KB of flows. Accumulating those across ~2k
# issues OOM'd the 512Mi Cloud Run job. Prune immediately after each page parse
# so peak RSS tracks mapper-needed bytes only.
_ISSUE_KEEP_FIELDS: frozenset[str] = frozenset(
    {
        "key",
        "project",
        "severity",
        "message",
        "rule",
        "creationDate",
        "component",
        "tags",
    }
)


def _prune_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Keep only mapper-needed fields; drop Sonar `flows` and other unused bulk."""
    return {k: issue[k] for k in _ISSUE_KEEP_FIELDS if k in issue}


def _fetch_all_issues(
    *,
    base_url: str,
    organization: str,
    token: str,
    client_factory=httpx.Client,
) -> list[dict[str, Any]]:
    """Walk `/api/issues/search` until exhausted or until we hit Sonar's 10k cap.

    Auth is HTTP Basic with the user token as the username and an empty password —
    this is the documented Sonar pattern for personal user tokens (project tokens
    use Bearer; we don't use those because they're per-project and we want one
    secret for the whole org).

    Each issue is pruned to mapper fields before accumulation (see `_prune_issue`).
    """
    headers = {
        "Accept": "application/json",
        "User-Agent": "secdb-sonarcloud-poller/0.1",
    }
    params_base = {
        "organization": organization,
        "types": "VULNERABILITY",
        "statuses": "OPEN,CONFIRMED,REOPENED",
        "ps": PAGE_SIZE,
    }
    out: list[dict[str, Any]] = []

    with client_factory(timeout=60.0, headers=headers, auth=(token, "")) as client:
        for page_index in range(1, HARD_PAGE_CAP + 1):
            params = {**params_base, "p": page_index}
            log.info("sonarcloud.fetch page=%d", page_index)
            response = client.get(f"{base_url.rstrip('/')}/api/issues/search", params=params)
            if response.status_code == 401:
                raise RuntimeError(
                    "sonarcloud: 401 — SONAR_TOKEN is invalid, expired, or lacks org access"
                )
            if response.status_code == 403:
                raise RuntimeError(
                    "sonarcloud: 403 — token has no read access to organization "
                    f"'{organization}'"
                )
            response.raise_for_status()

            body = response.json()
            issues = body.get("issues") or []
            paging = body.get("paging") or {}
            total = int(paging.get("total") or 0)
            page_size = int(paging.get("pageSize") or PAGE_SIZE)
            page_index_returned = int(paging.get("pageIndex") or page_index)
            page_len = len(issues)

            # Drop fat fields in-place before copying keepers — frees the
            # taint-analysis graphs for GC while we still hold the page body.
            for raw in issues:
                raw.pop("flows", None)
            out.extend(_prune_issue(i) for i in issues)
            del body, issues, response

            # Sonar returns the requested page even when empty; bail when we've
            # seen everything or when this page came back short.
            if len(out) >= total:
                break
            if page_len == 0:
                log.warning(
                    "sonarcloud: empty page %d before reaching total=%d (out=%d)",
                    page_index_returned,
                    total,
                    len(out),
                )
                break
            if total > HARD_PAGE_CAP * page_size and page_index == HARD_PAGE_CAP:
                log.warning(
                    "sonarcloud: hit pagination cap (%d issues), %d remaining unfetched. "
                    "Tighten the filter (e.g. by project) to access them.",
                    len(out),
                    total - len(out),
                )

    return out


def run() -> int:
    """Poll every SonarCloud org listed in `SONAR_ORGS` (or `SONAR_ORG`).

    All orgs are fetched and combined into a SINGLE snapshot envelope with one
    poll_id. This is critical for correctness with multiple orgs: the processor
    marks all sonarcloud findings NOT present in a snapshot as absent. If each org
    published a separate snapshot, the other org's findings would be marked absent
    on every poll, causing mass auto-close whenever Pub/Sub delivered two snapshots
    from the same org consecutively (threshold=2 hits after two misses). One combined
    snapshot eliminates cross-org contamination entirely.

    Each issue is tagged with `__org__` so the mapper can build the correct native_id
    and asset resolution per org even from the combined envelope. The per-issue tag
    is backward-compatible: old raw files (pre-combination) still have a top-level
    `organization` key that the mapper falls back to.

    A 401/403 against any org aborts the whole run — the operator has a token-scope
    problem worth surfacing.

    Returns 0 on full success, 2 on misconfiguration (no orgs, no token).
    """
    settings = get_settings()
    if not settings.sonar_orgs:
        log.error("sonarcloud: SONAR_ORGS (or SONAR_ORG) not set")
        return 2

    # Prefer the process env (Cloud Run injects SONAR_TOKEN via secret_key_ref).
    # Falling through to GSM loads grpc Secret Manager client (~hundreds of MiB)
    # and was a major contributor to 512Mi/1Gi out-of-memory failures alongside fat `flows`.
    token = os.environ.get("SONAR_TOKEN", "").strip()
    if not token:
        secrets = build_secret_backend(settings)
        token = secrets.get(SecretRef.sonarcloud_token()).strip()
    if not token:
        log.error("sonarcloud: SONAR_TOKEN is empty")
        return 2

    all_issues: list[dict] = []
    for organization in settings.sonar_orgs:
        issues = _fetch_all_issues(
            base_url=settings.sonar_base_url,
            organization=organization,
            token=token,
        )
        # Tag each issue with its org so the mapper can use it even after combining.
        for issue in issues:
            issue["__org__"] = organization
        all_issues.extend(issues)
        log.info("sonarcloud.fetched org=%s issues=%d", organization, len(issues))

    poll_id = uuid4()
    # Combined envelope: organization="" signals multi-org; mapper reads __org__ per issue.
    envelope = {"organization": "", "issues": all_issues}
    payload = json.dumps(envelope).encode("utf-8")

    raw_store = build_raw_store(settings)
    transport = build_ingest_transport(settings)
    raw_uri = raw_store.put(SONAR_SOURCE_NAME, poll_id, payload)

    log.info(
        "sonarcloud.snapshot orgs=%s poll_id=%s issues=%d raw_uri=%s",
        ",".join(settings.sonar_orgs),
        poll_id,
        len(all_issues),
        raw_uri,
    )
    transport.publish(SONAR_SOURCE_NAME, poll_id, raw_uri)
    log.info("sonarcloud.published orgs=%s poll_id=%s", ",".join(settings.sonar_orgs), poll_id)

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
