"""Wiz poller OAuth + fail-fast behaviour."""

from __future__ import annotations

import httpx
import respx

from app.pollers import wiz as wiz_poller
from app.pollers.wiz_queries import DETECTOR_BY_NAME

AUTH_URL = "https://auth.test/oauth/token"
API_URL = "https://api.test/graphql"


@respx.mock
def test_oauth_token_fetch() -> None:
    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-abc"})
    )
    token = wiz_poller.fetch_oauth_token(
        auth_url=AUTH_URL,
        client_id="id",
        client_secret="secret",
        audience="wiz-api",
    )
    assert token == "tok-abc"


@respx.mock
def test_fail_fast_on_graphql_error_does_not_publish(monkeypatch) -> None:
    class FakeSecrets:
        def get(self, _ref):
            return "test-secret"

    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )
    respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "boom"}], "data": None},
        )
    )

    published: list[tuple] = []

    class FakeStore:
        def put(self, source, poll_id, payload):
            raise AssertionError("should not write raw on failure")

    class FakeTransport:
        def publish(self, source, poll_id, raw_uri):
            published.append((source, poll_id, raw_uri))

    monkeypatch.setattr(wiz_poller, "build_raw_store", lambda _s: FakeStore())
    monkeypatch.setattr(wiz_poller, "build_ingest_transport", lambda _s: FakeTransport())
    monkeypatch.setattr(wiz_poller, "build_secret_backend", lambda _s: FakeSecrets())

    from app.core.config import Settings

    settings = Settings(
        wiz_api_url=API_URL,
        wiz_auth_url=AUTH_URL,
        wiz_oauth_audience="wiz-api",
    )
    code = wiz_poller.run(only_detector="issues", settings=settings)
    assert code == 1
    assert published == []


@respx.mock
def test_only_detector_produces_partial_envelope(monkeypatch) -> None:
    class FakeSecrets:
        def get(self, _ref):
            return "test-secret"

    respx.post(AUTH_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )
    spec = DETECTOR_BY_NAME["issues"]
    respx.post(API_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    spec.graphql_root: {
                        "nodes": [{"id": "n1", "severity": "HIGH", "status": "OPEN"}],
                        "pageInfo": {"hasNextPage": False},
                    }
                }
            },
        )
    )

    captured: dict = {}

    class FakeStore:
        def put(self, source, poll_id, payload):
            captured["payload"] = payload
            return "file:///wiz.json"

    class FakeTransport:
        def publish(self, source, poll_id, raw_uri):
            pass

    monkeypatch.setattr(wiz_poller, "build_raw_store", lambda _s: FakeStore())
    monkeypatch.setattr(wiz_poller, "build_ingest_transport", lambda _s: FakeTransport())
    monkeypatch.setattr(wiz_poller, "build_secret_backend", lambda _s: FakeSecrets())

    from app.core.config import Settings

    settings = Settings(wiz_api_url=API_URL, wiz_auth_url=AUTH_URL)
    assert wiz_poller.run(only_detector="issues", settings=settings) == 0
    import json

    body = json.loads(captured["payload"].decode())
    assert list(body.keys()) == ["issues"]
    assert len(body["issues"]) == 1
