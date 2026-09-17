"""Slack webhook notifications."""

from __future__ import annotations

import respx
from httpx import Response

from app.core.config import Settings, reset_settings_for_tests
from app.internal.slack import (
    notify_dlq_ingest_failure,
    notify_user_feedback,
    post_slack_message,
)


@respx.mock
def test_post_slack_incoming_webhook() -> None:
    reset_settings_for_tests()
    route = respx.post("https://hooks.slack.com/services/T/B/x").mock(
        return_value=Response(200, json={"ok": True})
    )
    settings = Settings(slack_webhook_url="https://hooks.slack.com/services/T/B/x")
    assert post_slack_message(text="hello", settings=settings) is True
    assert route.called
    import json

    body = json.loads(route.calls[0].request.content)
    assert body == {"text": "hello"}


@respx.mock
def test_post_slack_workflow_trigger() -> None:
    reset_settings_for_tests()
    url = "https://hooks.slack.com/triggers/T/1/secret"
    route = respx.post(url).mock(return_value=Response(200, json={"ok": True}))
    settings = Settings(slack_webhook_url=url)
    assert post_slack_message(
        text="alert",
        settings=settings,
        extra={"source": "dependabot"},
    )
    import json

    body = json.loads(route.calls[0].request.content)
    assert body["message"] == "alert"
    assert body["source"] == "dependabot"


@respx.mock
def test_notify_user_feedback_workflow_trigger() -> None:
    reset_settings_for_tests()
    url = "https://hooks.slack.com/triggers/T/1/secret"
    route = respx.post(url).mock(return_value=Response(200, json={"ok": True}))
    settings = Settings(slack_webhook_url=url)
    assert notify_user_feedback(
        kind="feedback",
        message="Great dashboard!",
        email="a@example.com",
        name="Alex ExampleOrg",
        page_url="/platform",
        settings=settings,
    )
    import json

    body = json.loads(route.calls[0].request.content)
    assert body["alert_type"] == "user_feedback"
    assert body["email"] == "a@example.com"
    assert body["name"] == "Alex ExampleOrg"
    assert body["page_url"] == "/platform"


@respx.mock
def test_notify_dlq_skips_without_webhook() -> None:
    reset_settings_for_tests()
    settings = Settings(slack_webhook_url="")
    notify_dlq_ingest_failure(
        source="dependabot",
        poll_id="p",
        raw_uri="gs://x",
        delivery_attempt=5,
        message_id="m",
        settings=settings,
    )
    assert len(respx.calls) == 0
