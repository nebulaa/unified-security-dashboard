"""OIDC verification for Pub/Sub push subscriptions."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import Settings, get_settings

log = logging.getLogger("secdb.pubsub_auth")


def _verify_oidc_token(token: str, audience: str) -> None:
    try:
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=audience,
        )
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            f"invalid pub/sub OIDC token: {exc}",
        ) from exc


async def verify_pubsub_oidc(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Require a valid Pub/Sub push OIDC token when `INGEST_TRANSPORT=pubsub`."""
    if settings.ingest_transport != "pubsub":
        return

    audience = settings.oidc_audience
    if not audience:
        log.warning("pubsub.oidc_skipped reason=missing_oidc_audience")
        return

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    token = auth.removeprefix("Bearer ").strip()
    _verify_oidc_token(token, audience)
