"""User feedback API."""

from __future__ import annotations

import json
import os

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.api.main import create_app
from app.core.config import reset_settings_for_tests

HDR = {"X-Dev-Identity": json.dumps({"email": "jane.doe@example.com", "name": "Jane Doe"})}
WEBHOOK = "https://hooks.slack.com/triggers/T/1/secret"


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


@respx.mock
def test_submit_feedback_posts_to_slack(client) -> None:
    reset_settings_for_tests()
    os.environ["SLACK_WEBHOOK_URL"] = WEBHOOK
    route = respx.post(WEBHOOK).mock(return_value=Response(200, json={"ok": True}))

    r = client.post(
        "/feedback",
        headers=HDR,
        json={
            "kind": "inaccuracy",
            "message": "SLA count looks wrong on Developer view.",
            "page_url": "/developer?team=order",
        },
    )

    assert r.status_code == 200
    assert r.json() == {"sent": True}
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert "Inaccuracy report" in body["message"]
    assert "jane.doe@example.com" in body["message"]
    assert "Jane Doe" in body["message"]
    assert "/developer?team=order" in body["message"]
    assert body["alert_type"] == "user_feedback"
    assert body["feedback_kind"] == "inaccuracy"


def test_submit_feedback_requires_webhook(client) -> None:
    reset_settings_for_tests()
    os.environ["SLACK_WEBHOOK_URL"] = ""
    r = client.post(
        "/feedback",
        headers=HDR,
        json={"message": "hello"},
    )
    assert r.status_code == 503


def test_me_includes_display_name(client) -> None:
    r = client.get("/me", headers=HDR)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "jane.doe@example.com"
    assert body["name"] == "Jane Doe"


def test_me_derives_name_from_email(client) -> None:
    hdr = {"X-Dev-Identity": json.dumps({"email": "john.smith@example.com"})}
    r = client.get("/me", headers=hdr)
    assert r.status_code == 200
    assert r.json()["name"] == "John Smith"
