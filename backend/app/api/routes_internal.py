"""Internal push endpoints (Pub/Sub config-changed on the API service)."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.pubsub_auth import verify_pubsub_oidc
from app.internal.config_reload import reload_all_config

router = APIRouter(prefix="/internal", tags=["internal"])


async def _parse_config_kind(request: Request) -> str | None:
    try:
        body = await request.json()
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    if not isinstance(message, dict):
        return None
    data_b64 = message.get("data")
    if not data_b64:
        return None
    try:
        payload = json.loads(base64.b64decode(data_b64).decode())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    kind = payload.get("config")
    return str(kind) if kind is not None else None


@router.post("/config-reload", dependencies=[Depends(verify_pubsub_oidc)])
async def config_reload(request: Request) -> dict[str, Any]:
    config_kind = await _parse_config_kind(request)
    return reload_all_config(config_kind=config_kind)
