"""DLQ handler and admin triage endpoints."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.models import DlqEvent
from app.normalizer.main import create_app as create_normalizer_app

ADMIN = {
    "X-Dev-Identity": json.dumps(
        {"email": "admin1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}
MEMBER = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


def _pubsub_wrap(payload: dict, *, message_id: str = "msg-1") -> dict:
    return {
        "message": {
            "messageId": message_id,
            "data": base64.b64encode(json.dumps(payload).encode()).decode(),
            "attributes": {},
        },
        "subscription": "projects/test/subscriptions/test",
    }


@pytest.fixture()
def api_client(session) -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def normalizer_client(session) -> TestClient:
    return TestClient(create_normalizer_app())


def test_dlq_handler_idempotent(normalizer_client, session) -> None:
    body = _pubsub_wrap(
        {"source": "dependabot", "poll_id": "00000000-0000-0000-0000-000000000099", "raw_uri": "gs://x"},
        message_id="dup-1",
    )
    with patch("app.normalizer.main.notify_dlq_ingest_failure") as notify:
        r1 = normalizer_client.post("/internal/dlq", json=body)
    assert r1.status_code == 200
    assert r1.json()["inserted"] is True
    notify.assert_called_once()

    with patch("app.normalizer.main.notify_dlq_ingest_failure") as notify2:
        r2 = normalizer_client.post("/internal/dlq", json=body)
    assert r2.status_code == 200
    assert r2.json()["inserted"] is False
    notify2.assert_not_called()

    assert session.query(DlqEvent).count() == 1


def test_admin_dlq_list_and_resolve(api_client, session, normalizer_client) -> None:
    normalizer_client.post(
        "/internal/dlq",
        json=_pubsub_wrap(
            {"source": "sonarcloud", "poll_id": "00000000-0000-0000-0000-000000000088", "raw_uri": "gs://y"},
            message_id="admin-test-1",
        ),
    )
    session.commit()

    denied = api_client.get("/admin/dlq", headers=MEMBER)
    assert denied.status_code == 403

    listed = api_client.get("/admin/dlq", headers=ADMIN)
    assert listed.status_code == 200
    body = listed.json()
    assert body["unresolved_count"] >= 1
    event_id = body["items"][0]["id"]

    resolved = api_client.post(f"/admin/dlq/{event_id}/resolve", headers=ADMIN)
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"] == "admin1@example.com"
    assert resolved.json()["resolved_at"] is not None
