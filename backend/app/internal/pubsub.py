"""Pub/Sub push envelope helpers."""

from __future__ import annotations

import base64
import json
from typing import Any

from fastapi import HTTPException, status


def unwrap_pubsub_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return the application payload, unwrapping a Pub/Sub envelope if present."""
    if "message" in body and isinstance(body["message"], dict):
        msg = body["message"]
        data = msg.get("data")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "pub/sub message missing data")
        try:
            return json.loads(base64.b64decode(data))
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"invalid pub/sub data payload: {exc}"
            ) from exc
    return body


def pubsub_message_id(body: dict[str, Any]) -> str | None:
    if "message" in body and isinstance(body["message"], dict):
        mid = body["message"].get("messageId") or body["message"].get("message_id")
        if mid:
            return str(mid)
    return None


def delivery_attempt_from_request(request_headers: dict[str, str]) -> int:
    """Parse CloudEvents `Ce-Deliveryattempt` or Pub/Sub extension header."""
    for key in ("ce-deliveryattempt", "Ce-Deliveryattempt", "x-goog-pubsub-delivery-attempt"):
        raw = request_headers.get(key)
        if raw:
            try:
                return int(raw)
            except ValueError:
                pass
    return 1
