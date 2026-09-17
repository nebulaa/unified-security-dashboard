"""Teams directory endpoint — backs the team filter dropdown in the UI."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


HDR = {
    "X-Dev-Identity": json.dumps({"email": "dev1@example.com"}),
}


def test_list_teams_returns_fixture_teams_sorted(client) -> None:
    r = client.get("/teams", headers=HDR)
    assert r.status_code == 200
    body = r.json()

    names = [i["name"] for i in body["items"]]
    # The fixture defines generic product, retail, and platform teams plus the sentinel.
    # `unowned` has no pillar so it must sort last (pillar=None bucket).
    assert set(names) == {
        "pricing-platform",
        "data-platform",
        "io-data-eng",
        "io-platform-eng",
        "product-platform",
        "platform-retail",
        "unowned",
    }
    assert names[-1] == "unowned"


def test_list_teams_exposes_pillar_metadata(client) -> None:
    r = client.get("/teams", headers=HDR)
    by_name = {i["name"]: i for i in r.json()["items"]}

    pp = by_name["pricing-platform"]
    assert pp["display_name"] == "Pricing Platform (test)"
    assert pp["pillar"] == "product"
    assert pp["pillar_name"] == "Product"

    ide = by_name["io-data-eng"]
    assert ide["pillar"] == "io"

    # `unowned` has no pillar in the fixture
    assert by_name["unowned"]["pillar"] is None
    assert by_name["unowned"]["pillar_name"] is None
    assert by_name["pricing-platform"]["jira_project"] is None
    assert by_name["pricing-platform"]["engineering_manager_name"] is None
    assert by_name["pricing-platform"]["security_poc_name"] is None


def test_list_teams_requires_auth(client) -> None:
    r = client.get("/teams")
    assert r.status_code == 401
