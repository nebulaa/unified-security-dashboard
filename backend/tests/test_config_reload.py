"""On-change config reload push endpoint."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.main import create_app
from app.core.enums import EventType, Severity
from app.core.models import Finding, FindingEvent
from app.internal.config_reload import reload_all_config
from app.normalizer.main import create_app as create_normalizer_app
from tests._factory import make_finding


def _pubsub_wrap(payload: dict) -> dict:
    return {
        "message": {
            "messageId": "cfg-1",
            "data": base64.b64encode(json.dumps(payload).encode()).decode(),
        }
    }


@pytest.fixture()
def api_client(session) -> TestClient:
    return TestClient(create_app())


@pytest.fixture()
def normalizer_client(session) -> TestClient:
    return TestClient(create_normalizer_app())


def test_config_reload_api(api_client) -> None:
    with patch("app.api.routes_internal.reload_all_config") as reload:
        reload.return_value = {"status": "reloaded", "owner_team_updates": 0}
        r = api_client.post("/internal/config-reload", json=_pubsub_wrap({"config": "ownership"}))
    assert r.status_code == 200
    assert r.json()["status"] == "reloaded"
    reload.assert_called_once_with(config_kind="ownership")


def test_config_reload_normalizer(normalizer_client) -> None:
    with patch("app.normalizer.main.reload_caches") as reload:
        r = normalizer_client.post(
            "/internal/config-reload", json=_pubsub_wrap({"config": "rbac"})
        )
    assert r.status_code == 200
    reload.assert_called_once()


def test_reload_rbac_skips_reresolve(session) -> None:
    finding = make_finding(session, native_id="rbac-skip#1", owner_team="unowned")
    session.commit()

    out = reload_all_config(config_kind="rbac")
    assert out["owner_team_updates"] == 0

    session.expire_all()
    refreshed = session.get(Finding, finding.id)
    assert refreshed.owner_team == "unowned"


def test_reload_reresolves_owner_teams(session) -> None:
    finding = make_finding(
        session,
        native_id="ExampleOrg/example-service#1",
        severity=Severity.high,
        owner_team="unowned",
    )
    session.commit()

    with patch("app.internal.config_reload.maybe_trigger_rollup_backfill", return_value=False):
        reload_all_config(config_kind="ownership")

    session.expire_all()
    refreshed = session.get(Finding, finding.id)
    assert refreshed is not None
    assert refreshed.owner_team == "pricing-platform"

    events = session.execute(
        select(FindingEvent).where(
            FindingEvent.finding_id == finding.id,
            FindingEvent.event_type == EventType.ownership_changed,
        )
    ).scalars().all()
    assert len(events) == 1
    assert events[0].actor == "system:config_reload"
