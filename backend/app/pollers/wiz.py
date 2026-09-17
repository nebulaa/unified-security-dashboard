"""Wiz poller — OAuth2 + 3 scheduled GraphQL detectors + Threat Center.

Locally:
    make poller-wiz
    python -m app.pollers.wiz --only-detector vulnerability_findings
    python -m app.pollers.wiz --backfill   # first-run 90-day window (wiz_backfill_days)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from app.adapters.ingest_transport import build_ingest_transport
from app.adapters.raw_store import build_raw_store
from app.adapters.secrets import SecretRef, build_secret_backend
from app.core.config import Settings, get_settings
from app.core.wiz_threat_center_fetch import poll_impacted_threat_center_items
from app.pollers.wiz_queries import (
    DETECTOR_BY_NAME,
    SCHEDULED_DETECTORS,
    STUB_ENVELOPE_KEYS,
    DetectorSpec,
)

log = logging.getLogger("secdb.pollers.wiz")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

WIZ_SOURCE = "wiz"
PAGE_SIZE = 500


def fetch_oauth_token(
    *,
    auth_url: str,
    client_id: str,
    client_secret: str,
    audience: str,
    client: httpx.Client | None = None,
) -> str:
    """Obtain a bearer token via client credentials."""
    payload = {
        "grant_type": "client_credentials",
        "audience": audience,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    own = client is None
    http = client or httpx.Client(timeout=60.0)
    try:
        # Wiz IdP expects form-urlencoded body, not JSON (docs.wiz.io / wizapi SDK).
        response = http.post(
            auth_url,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code == 401:
            raise RuntimeError("wiz: OAuth 401 — client id/secret invalid or expired")
        if response.status_code == 400:
            detail = response.text.strip() or "(empty body)"
            hint = (
                "Wiz returned 400 for a known client_id — usually the client_secret is "
                "wrong, expired, or copied from a different service account. In Wiz: "
                "Settings → Service Accounts → your GraphQL integration → regenerate "
                "secret, then update WIZ_CLIENT_SECRET. Confirm the token URL on that "
                "page matches WIZ_AUTH_URL (Cognito: auth.app.wiz.io; Auth0: auth.wiz.io)."
            )
            raise RuntimeError(f"wiz: OAuth 400 ({detail}). {hint}")
        response.raise_for_status()
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise RuntimeError(f"wiz: OAuth response missing access_token: {body!r}")
        return str(token)
    finally:
        if own:
            http.close()


def _graphql_errors(data: dict[str, Any]) -> list[dict[str, Any]]:
    errors = data.get("errors")
    if isinstance(errors, list):
        return errors
    return []


def paginate_detector(
    *,
    api_url: str,
    token: str,
    spec: DetectorSpec,
    backfill: bool,
    backfill_after: str | None,
    client: httpx.Client,
) -> list[dict[str, Any]]:
    """Fetch all pages for one detector. Raises on GraphQL or HTTP errors."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    nodes: list[dict[str, Any]] = []
    after: str | None = None
    filter_by = spec.build_filter(backfill=backfill, backfill_after=backfill_after)

    while True:
        variables: dict[str, Any] = {
            "first": PAGE_SIZE,
            "filterBy": filter_by,
        }
        if after:
            variables["after"] = after

        response = client.post(
            api_url,
            headers=headers,
            json={"query": spec.query, "variables": variables},
        )
        if response.status_code == 401:
            raise RuntimeError("wiz: GraphQL 401 — token invalid or expired")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        gql_errors = _graphql_errors(payload)
        if gql_errors or response.status_code >= 400:
            messages = "; ".join(str(e.get("message", e)) for e in gql_errors)
            if not messages:
                messages = response.text.strip() or f"HTTP {response.status_code}"
            raise RuntimeError(
                f"wiz: GraphQL error on detector {spec.name!r}: {messages}"
            )

        data = payload.get("data") or {}
        connection = data.get(spec.graphql_root)
        if connection is None:
            raise RuntimeError(
                f"wiz: GraphQL response missing root {spec.graphql_root!r} "
                f"for detector {spec.name!r}"
            )

        page_nodes = connection.get("nodes") or []
        if not isinstance(page_nodes, list):
            raise RuntimeError(
                f"wiz: unexpected nodes shape for {spec.name!r}: {type(page_nodes).__name__}"
            )
        nodes.extend(page_nodes)

        page_info = connection.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            after = page_info.get("endCursor")
            if not after:
                break
        else:
            break

    return nodes


def _backfill_cutoff_iso(settings: Settings) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=settings.wiz_backfill_days)
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


def run(
    *,
    only_detector: str | None = None,
    backfill: bool = False,
    settings: Settings | None = None,
) -> int:
    s = settings or get_settings()
    if not s.wiz_api_url:
        log.error("wiz: WIZ_API_URL not set")
        return 2

    specs = SCHEDULED_DETECTORS
    if only_detector:
        spec = DETECTOR_BY_NAME.get(only_detector)
        if spec is None:
            log.error("wiz: unknown detector %r (choices: %s)", only_detector, sorted(DETECTOR_BY_NAME))
            return 2
        specs = (spec,)

    secrets = build_secret_backend(s)
    client_id = secrets.get(SecretRef.wiz_client_id())
    client_secret = secrets.get(SecretRef.wiz_client_secret())

    backfill_after = _backfill_cutoff_iso(s) if backfill else None
    if backfill:
        log.info("wiz.backfill window after=%s days=%d", backfill_after, s.wiz_backfill_days)

    envelope: dict[str, list[dict[str, Any]]] = {}

    with httpx.Client(timeout=120.0) as client:
        token = fetch_oauth_token(
            auth_url=s.wiz_auth_url,
            client_id=client_id,
            client_secret=client_secret,
            audience=s.wiz_oauth_audience,
            client=client,
        )
        for spec in specs:
            log.info("wiz.fetch detector=%s", spec.name)
            try:
                nodes = paginate_detector(
                    api_url=s.wiz_api_url,
                    token=token,
                    spec=spec,
                    backfill=backfill,
                    backfill_after=backfill_after,
                    client=client,
                )
            except Exception:
                log.exception("wiz.fetch_failed detector=%s — aborting poll", spec.name)
                return 1
            envelope[spec.envelope_key] = nodes
            log.info("wiz.fetch_done detector=%s count=%d", spec.name, len(nodes))

        if only_detector is None:
            log.info("wiz.fetch detector=threat_center days=%d", s.wiz_threat_center_days)
            try:
                threat_nodes = poll_impacted_threat_center_items(
                    api_url=s.wiz_api_url,
                    token=token,
                    days=s.wiz_threat_center_days,
                    client=client,
                )
            except Exception:
                log.exception("wiz.fetch_failed detector=threat_center — aborting poll")
                return 1
            envelope["threat_center"] = threat_nodes
            log.info("wiz.fetch_done detector=threat_center count=%d", len(threat_nodes))

    # Full scheduled polls always emit all envelope keys; `--only-detector` is partial.
    if only_detector is None:
        for stub_key in STUB_ENVELOPE_KEYS:
            envelope.setdefault(stub_key, [])

    total = sum(len(v) for v in envelope.values())
    poll_id = uuid4()
    raw_store = build_raw_store(s)
    transport = build_ingest_transport(s)
    payload = json.dumps(envelope).encode("utf-8")
    raw_uri = raw_store.put(WIZ_SOURCE, poll_id, payload)

    log.info("wiz.snapshot poll_id=%s findings=%d raw_uri=%s", poll_id, total, raw_uri)
    transport.publish(WIZ_SOURCE, poll_id, raw_uri)
    log.info("wiz.published poll_id=%s", poll_id)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiz connector poller")
    parser.add_argument(
        "--only-detector",
        choices=sorted(DETECTOR_BY_NAME),
        help="Fetch a single detector (partial envelope — local debugging only)",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Apply firstSeenAt window (wiz_backfill_days) in addition to open filters",
    )
    args = parser.parse_args()
    sys.exit(run(only_detector=args.only_detector, backfill=args.backfill))


if __name__ == "__main__":
    main()
