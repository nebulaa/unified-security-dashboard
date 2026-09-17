"""Dependabot poller (Cloud Run Job in prod, plain CLI command locally).

Fetches `GET /orgs/{org}/dependabot/alerts?state=open`, follows pagination, writes the
full assembled snapshot to the configured raw store, and publishes a single
`{source, poll_id, raw_uri}` ingest message.

Auth (prototype): personal access token from Secret Manager (env in dev),.
Production graduation replaces this with a GitHub App + installation token.

Locally:
    make poller-dependabot
    # or:
    python -m app.pollers.dependabot
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any
from uuid import uuid4

import httpx

from app.adapters.ingest_transport import build_ingest_transport
from app.adapters.raw_store import build_raw_store
from app.adapters.secrets import SecretRef, build_secret_backend
from app.core.config import get_settings

log = logging.getLogger("secdb.pollers.dependabot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

GITHUB_API = "https://api.github.com"
ALERTS_PER_PAGE = 100


def _fetch_all_alerts(org: str, token: str) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "secdb-dependabot-poller/0.1",
    }
    url: str | None = (
        f"{GITHUB_API}/orgs/{org}/dependabot/alerts?state=open&per_page={ALERTS_PER_PAGE}"
    )
    out: list[dict[str, Any]] = []

    with httpx.Client(timeout=60.0, headers=headers) as client:
        while url:
            log.info("dependabot.fetch url=%s", url)
            response = client.get(url)
            if response.status_code == 401:
                raise RuntimeError("dependabot: 401 — PAT is invalid or expired")
            if response.status_code == 403:
                raise RuntimeError(
                    "dependabot: 403 — see scopes/role checklist: classic PAT needs "
                    "security_events; account must be org Owner or Security manager; "
                    "if org uses SAML SSO authorize the token; Dependabot alerts must "
                    "be enabled. Run: ./scripts/rotate-dependabot-pat.sh --check-only"
                )
            response.raise_for_status()
            page = response.json()
            if not isinstance(page, list):
                raise RuntimeError(f"dependabot: unexpected response shape: {type(page).__name__}")
            out.extend(page)

            next_link = response.links.get("next")
            url = next_link["url"] if next_link else None

    return out


def run() -> int:
    settings = get_settings()
    if not settings.github_org:
        log.error("dependabot: GITHUB_ORG not set")
        return 2

    secrets = build_secret_backend(settings)
    raw_store = build_raw_store(settings)
    transport = build_ingest_transport(settings)

    pat = secrets.get(SecretRef.dependabot_pat())
    alerts = _fetch_all_alerts(settings.github_org, pat)

    poll_id = uuid4()
    payload = json.dumps(alerts).encode("utf-8")
    raw_uri = raw_store.put("dependabot", poll_id, payload)

    log.info("dependabot.snapshot poll_id=%s alerts=%d raw_uri=%s", poll_id, len(alerts), raw_uri)
    transport.publish("dependabot", poll_id, raw_uri)
    log.info("dependabot.published poll_id=%s", poll_id)
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
