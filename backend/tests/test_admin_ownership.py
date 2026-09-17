"""Admin ownership re-resolution API."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.internal.ownership_trigger import OwnershipReresolveRunResult

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


def test_admin_ownership_status_rbac(api_client) -> None:
    denied = api_client.get("/admin/ownership", headers=MEMBER)
    assert denied.status_code == 403

    ok = api_client.get("/admin/ownership", headers=ADMIN)
    assert ok.status_code == 200
    body = ok.json()
    assert "owner_team_counts" in body
    assert "unowned_count" in body
    assert "trigger_mode" in body


def test_admin_ownership_reresolve_local(api_client) -> None:
    with patch(
        "app.api.routes_admin_ownership.trigger_ownership_reresolve",
        return_value=OwnershipReresolveRunResult(
            mode="local",
            job_name=None,
            execution_name=None,
            rollup_execution_name=None,
            message="Re-resolved 3 findings",
            result={
                "scanned": 100,
                "updated": 3,
                "by_transition": {"unowned->pricing-platform": 3},
                "rollup_triggered": True,
            },
        ),
    ) as mock_trigger:
        denied = api_client.post("/admin/ownership/reresolve", headers=MEMBER)
        assert denied.status_code == 403

        res = api_client.post("/admin/ownership/reresolve", headers=ADMIN)
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "local"
    assert body["updated"] == 3
    assert body["rollup_triggered"] is True
    mock_trigger.assert_called_once()
