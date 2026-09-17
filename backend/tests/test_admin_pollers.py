"""Admin poller trigger API."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.internal.poller_trigger import PollerRunResult

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


@pytest.fixture()
def api_client(session) -> TestClient:
    return TestClient(create_app())


def test_admin_pollers_list(api_client) -> None:
    denied = api_client.get("/admin/pollers", headers=MEMBER)
    assert denied.status_code == 403

    listed = api_client.get("/admin/pollers", headers=ADMIN)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body["items"]) == 4
    sources = {i["source"] for i in body["items"]}
    assert sources == {"dependabot", "sonarcloud", "wiz", "pentest"}


def test_admin_pollers_run_local(api_client) -> None:
    with patch(
        "app.api.routes_admin_pollers.trigger_poller",
        return_value=PollerRunResult(
            source="dependabot",
            mode="local",
            job_name=None,
            execution_name=None,
            message="Local poller dependabot started in background",
        ),
    ) as mock_trigger:
        res = api_client.post("/admin/pollers/dependabot/run", headers=ADMIN)
    assert res.status_code == 200
    assert res.json()["mode"] == "local"
    mock_trigger.assert_called_once_with("dependabot")


def test_admin_pollers_wiz_run_local(api_client) -> None:
    with patch(
        "app.api.routes_admin_pollers.trigger_poller",
        return_value=PollerRunResult(
            source="wiz",
            mode="local",
            job_name=None,
            execution_name=None,
            message="Local poller wiz started in background",
        ),
    ) as mock_trigger:
        res = api_client.post("/admin/pollers/wiz/run", headers=ADMIN)
    assert res.status_code == 200
    mock_trigger.assert_called_once_with("wiz")
