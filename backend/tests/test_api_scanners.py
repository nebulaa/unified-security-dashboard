"""Scanner health endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.models import ProcessedPayload


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


HDR = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


def test_scanner_health_classifies_active_stale_dark_no_data(session, client) -> None:
    now = datetime.now(UTC)
    session.add(
        ProcessedPayload(
            source="dependabot",
            poll_id=uuid4(),
            raw_uri="file:///tmp/x.json",
            processed_at=now - timedelta(seconds=30),
            finding_count=0,
        )
    )
    session.add(
        ProcessedPayload(
            source="sonarcloud",
            poll_id=uuid4(),
            raw_uri="file:///tmp/x.json",
            processed_at=now - timedelta(hours=2),  # > 1x cadence (3600s), < 3x
            finding_count=0,
        )
    )
    session.add(
        ProcessedPayload(
            source="wiz",
            poll_id=uuid4(),
            raw_uri="file:///tmp/x.json",
            processed_at=now - timedelta(hours=5),  # > 3x cadence (1800s)
            finding_count=0,
        )
    )
    session.commit()

    r = client.get("/scanners/health", headers=HDR)
    assert r.status_code == 200
    body = r.json()
    by_source = {i["source"]: i for i in body["items"]}

    assert by_source["dependabot"]["status"] == "active"
    assert by_source["sonarcloud"]["status"] == "stale"
    assert by_source["wiz"]["status"] == "dark"
    assert by_source["nuclei"]["status"] == "no_data"
    assert body["total"] == 7
