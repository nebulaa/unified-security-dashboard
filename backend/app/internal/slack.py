"""Post operator alerts to Slack (incoming webhook or Workflow trigger).

Supports:
  - Incoming webhooks: `https://hooks.slack.com/services/...` → body `{"text": "..."}`
  - Workflow triggers: `https://hooks.slack.com/triggers/...` → body `{"message": "..."}`
    plus optional structured keys for DLQ alerts (map them in the workflow).

Configure via `SLACK_WEBHOOK_URL` / Secret Manager `secdb-slack-webhook`. For Workflow
triggers the target channel is set in the workflow (e.g. C0B555T3Z5X).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.adapters.secrets import SecretRef, build_secret_backend
from app.core.config import Settings, get_settings

log = logging.getLogger("secdb.slack")

_SLACK_TIMEOUT = 10.0


def resolve_slack_webhook_url(settings: Settings | None = None) -> str | None:
    """Return webhook URL when configured; None disables notifications."""
    s = settings or get_settings()
    direct = (s.slack_webhook_url or "").strip()
    if direct:
        return direct
    if s.secret_backend == "env":
        return (os.environ.get("SLACK_WEBHOOK_URL") or "").strip() or None
    try:
        url = build_secret_backend(s).get(SecretRef.slack_webhook()).strip()
    except Exception:
        log.debug("slack.webhook_unavailable", exc_info=True)
        return None
    if not url or url.startswith("REPLACE"):
        return None
    return url


def _is_workflow_trigger(url: str) -> bool:
    return "/triggers/" in url


def _build_payload(url: str, *, text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    if _is_workflow_trigger(url):
        body: dict[str, Any] = {"message": text}
        if extra:
            body.update(extra)
        return body
    return {"text": text}


def post_slack_message(
    *,
    text: str,
    settings: Settings | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Post to Slack. Returns True if sent, False if skipped."""
    url = resolve_slack_webhook_url(settings)
    if not url:
        log.debug("slack.skip reason=no_webhook")
        return False
    try:
        response = httpx.post(
            url,
            json=_build_payload(url, text=text, extra=extra),
            timeout=_SLACK_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except Exception:
        log.warning("slack.post_failed", exc_info=True)
        return False


def notify_user_feedback(
    *,
    kind: str,
    message: str,
    email: str,
    name: str,
    page_url: str | None = None,
    settings: Settings | None = None,
) -> bool:
    """Post dashboard feedback or an inaccuracy report from an authenticated user."""
    label = "Inaccuracy report" if kind == "inaccuracy" else "Feedback"
    emoji = ":mag:" if kind == "inaccuracy" else ":speech_balloon:"
    lines = [
        f"{emoji} *Security Dashboard — {label}*",
        f"From: *{name}* (`{email}`)",
    ]
    if page_url:
        lines.append(f"Page: `{page_url}`")
    lines.append(f"\n{message}")
    return post_slack_message(
        text="\n".join(lines),
        settings=settings,
        extra={
            "alert_type": "user_feedback",
            "feedback_kind": kind,
            "email": email,
            "name": name,
            "page_url": page_url or "",
            "feedback_message": message,
        },
    )


def notify_dlq_ingest_failure(
    *,
    source: str | None,
    poll_id: str | None,
    raw_uri: str | None,
    delivery_attempt: int,
    message_id: str,
    settings: Settings | None = None,
) -> None:
    lines = [
        ":warning: *Security Dashboard — ingest failed (DLQ)*",
        f"Source: `{source or 'unknown'}`",
        f"Poll: `{poll_id or '—'}`",
        f"Raw: `{raw_uri or '—'}`",
        f"Pub/Sub message: `{message_id}`",
        f"Delivery attempts: {delivery_attempt}",
        "Triage in Admin → Failed ingests (DLQ).",
    ]
    post_slack_message(
        text="\n".join(lines),
        settings=settings,
        extra={
            "alert_type": "dlq_ingest_failure",
            "source": source or "",
            "poll_id": poll_id or "",
            "raw_uri": raw_uri or "",
            "message_id": message_id,
            "delivery_attempt": delivery_attempt,
        },
    )
