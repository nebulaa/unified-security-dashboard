"""Pin the SonarCloud poller's request shape, pagination, and error handling
.

Tests use respx to mock httpx so we never hit sonarcloud.io. The poller is wired
through `_fetch_all_issues(client_factory=...)` to keep the test plumbing local
without monkeypatching at module level.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app.pollers.sonarcloud import _fetch_all_issues, _prune_issue

BASE = "https://sonarcloud.io"
ORG = "exampleorg"


def test_prune_issue_drops_flows_and_unused_fields() -> None:
    """Mapper-needed fields survive; Sonar taint `flows` (and other bulk) do not.

    A single cpp:S5145 issue can carry ~600KB of flows — that OOM'd the 512Mi
    Cloud Run job when accumulated across the snapshot. Pin the keep-list so a
    casual field add to the mapper forces an explicit poller update.
    """
    pruned = _prune_issue(
        {
            "key": "AY-1",
            "project": "exampleorg_sample-service",
            "severity": "BLOCKER",
            "message": "tainted value 'args' is leaking",
            "rule": "cpp:S5145",
            "creationDate": "2025-07-01T13:27:34+0000",
            "component": "exampleorg_sample-service:src/a.cpp",
            "tags": ["cwe:cwe-20"],
            "flows": [{"locations": [{"msg": "x" * 1000} for _ in range(200)]}],
            "debt": "30min",
            "effort": "30min",
            "impacts": [{"softwareQuality": "SECURITY", "severity": "HIGH"}],
            "cleanCodeAttribute": "COMPLETE",
            "author": "dev@example.com",
            "status": "OPEN",
        }
    )
    assert pruned == {
        "key": "AY-1",
        "project": "exampleorg_sample-service",
        "severity": "BLOCKER",
        "message": "tainted value 'args' is leaking",
        "rule": "cpp:S5145",
        "creationDate": "2025-07-01T13:27:34+0000",
        "component": "exampleorg_sample-service:src/a.cpp",
        "tags": ["cwe:cwe-20"],
    }
    assert "flows" not in pruned


@respx.mock
def test_fetch_prunes_issues_before_returning() -> None:
    """End-to-end through `_fetch_all_issues`: fat Sonar fields never leave the page."""
    fat_page = _issues_page(page_index=1, page_size=500, total=1, keys=["FAT"])
    fat_page["issues"][0]["flows"] = [{"locations": [{"msg": "bulk"}]}]
    fat_page["issues"][0]["debt"] = "30min"
    fat_page["issues"][0]["component"] = "exampleorg_product-core:src/A.java"
    fat_page["issues"][0]["tags"] = ["cwe:cwe-79"]
    respx.get(f"{BASE}/api/issues/search").mock(
        return_value=httpx.Response(200, json=fat_page)
    )

    issues = _fetch_all_issues(base_url=BASE, organization=ORG, token="t")

    assert len(issues) == 1
    assert set(issues[0]) == {
        "key",
        "project",
        "severity",
        "message",
        "rule",
        "creationDate",
        "component",
        "tags",
    }
    assert "flows" not in issues[0]
    assert "debt" not in issues[0]


def _issues_page(
    *,
    page_index: int,
    page_size: int,
    total: int,
    keys: list[str],
) -> dict[str, Any]:
    return {
        "paging": {"pageIndex": page_index, "pageSize": page_size, "total": total},
        "issues": [
            {
                "key": k,
                "project": "exampleorg_product-core",
                "severity": "BLOCKER",
                "message": f"vuln {k}",
                "rule": "java:S2076",
                "creationDate": "2025-09-01T12:34:56+0000",
            }
            for k in keys
        ],
    }


@respx.mock
def test_pagination_walks_until_total_reached() -> None:
    """Sonar `paging.total` drives the loop. Two pages of 2 issues each at ps=500
    means we still stop after seeing 4."""
    route = respx.get(f"{BASE}/api/issues/search").mock(
        side_effect=[
            httpx.Response(200, json=_issues_page(
                page_index=1, page_size=500, total=4, keys=["A", "B"],
            )),
            httpx.Response(200, json=_issues_page(
                page_index=2, page_size=500, total=4, keys=["C", "D"],
            )),
        ]
    )

    issues = _fetch_all_issues(base_url=BASE, organization=ORG, token="t")

    assert [i["key"] for i in issues] == ["A", "B", "C", "D"]
    assert route.call_count == 2
    # Verify the contract: org + types + statuses + ps params on every call.
    first = route.calls[0].request
    assert "organization=exampleorg" in str(first.url)
    assert "types=VULNERABILITY" in str(first.url)
    assert "OPEN%2CCONFIRMED%2CREOPENED" in str(first.url) or "OPEN,CONFIRMED,REOPENED" in str(first.url)
    assert "ps=500" in str(first.url)


@respx.mock
def test_basic_auth_uses_token_as_username() -> None:
    """Sonar personal user tokens are sent as HTTP Basic with token-as-username,
    empty password. Pinning this so we don't accidentally regress to Bearer."""
    respx.get(f"{BASE}/api/issues/search").mock(
        return_value=httpx.Response(200, json=_issues_page(
            page_index=1, page_size=500, total=0, keys=[],
        ))
    )

    _fetch_all_issues(base_url=BASE, organization=ORG, token="my-token-abc")

    auth_header = respx.calls.last.request.headers["authorization"]
    # base64("my-token-abc:") = "bXktdG9rZW4tYWJjOg=="
    assert auth_header == "Basic bXktdG9rZW4tYWJjOg=="


@respx.mock
def test_401_raises_helpful_error() -> None:
    respx.get(f"{BASE}/api/issues/search").mock(return_value=httpx.Response(401))

    with pytest.raises(RuntimeError, match="SONAR_TOKEN is invalid"):
        _fetch_all_issues(base_url=BASE, organization=ORG, token="bad")


@respx.mock
def test_403_raises_org_access_error() -> None:
    respx.get(f"{BASE}/api/issues/search").mock(return_value=httpx.Response(403))

    with pytest.raises(RuntimeError, match="no read access to organization"):
        _fetch_all_issues(base_url=BASE, organization=ORG, token="t")


@respx.mock
def test_empty_first_page_returns_empty() -> None:
    respx.get(f"{BASE}/api/issues/search").mock(
        return_value=httpx.Response(200, json=_issues_page(
            page_index=1, page_size=500, total=0, keys=[],
        ))
    )

    assert _fetch_all_issues(base_url=BASE, organization=ORG, token="t") == []


@respx.mock
def test_short_page_breaks_early() -> None:
    """Defensive: if Sonar returns an empty page before reaching `total` (their
    bug, not ours), we stop instead of looping forever."""
    respx.get(f"{BASE}/api/issues/search").mock(
        side_effect=[
            httpx.Response(200, json=_issues_page(
                page_index=1, page_size=500, total=999, keys=["A", "B"],
            )),
            httpx.Response(200, json={"paging": {"pageIndex": 2, "pageSize": 500, "total": 999}, "issues": []}),
        ]
    )

    issues = _fetch_all_issues(base_url=BASE, organization=ORG, token="t")
    assert [i["key"] for i in issues] == ["A", "B"]


def test_run_refuses_when_sonar_org_missing(monkeypatch) -> None:
    """End-to-end: `run()` short-circuits with rc=2 instead of attempting any
    network call when SONAR_ORG/SONAR_ORGS is empty."""
    from app.core import config as cfg_mod
    from app.pollers import sonarcloud as poller_mod

    cfg_mod.reset_settings_for_tests()
    monkeypatch.setenv("SONAR_ORG", "")
    monkeypatch.delenv("SONAR_ORGS", raising=False)
    # Token MUST also be empty/unset so secrets adapter isn't consulted.
    monkeypatch.delenv("SONAR_TOKEN", raising=False)

    rc = poller_mod.run()
    assert rc == 2

    cfg_mod.reset_settings_for_tests()


def test_run_refuses_when_token_empty(monkeypatch, tmp_path) -> None:
    """If SONAR_ORGS is set but SONAR_TOKEN is empty, the secrets backend itself
    raises (`secret not set in env`). We accept either rc=2 or RuntimeError so
    this contract holds regardless of where in the chain the empty check fires."""
    from app.core import config as cfg_mod
    from app.pollers import sonarcloud as poller_mod

    cfg_mod.reset_settings_for_tests()
    monkeypatch.setenv("SONAR_ORG", "exampleorg")
    monkeypatch.delenv("SONAR_ORGS", raising=False)
    monkeypatch.delenv("SONAR_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="SONAR_TOKEN"):
        poller_mod.run()

    cfg_mod.reset_settings_for_tests()


def test_settings_accepts_csv_sonar_orgs(monkeypatch) -> None:
    """`SONAR_ORG=exampleorg,exampledivision` should populate `Settings.sonar_orgs` as a
    list with insertion order preserved (drives poll order). Pinning the CSV
    parse so a single edit can switch the org count from 1 to N without
    touching the poller or mapper."""
    from app.core import config as cfg_mod

    cfg_mod.reset_settings_for_tests()
    monkeypatch.setenv("SONAR_ORG", "exampleorg, exampledivision ,exampleorg")  # whitespace + dupe
    settings = cfg_mod.get_settings()
    assert settings.sonar_orgs == ["exampleorg", "exampledivision"]  # deduped, ordered

    cfg_mod.reset_settings_for_tests()


def test_settings_accepts_sonar_orgs_alias(monkeypatch) -> None:
    """Both `SONAR_ORG` (legacy) and `SONAR_ORGS` (plural) populate the same
    list — operators migrating from single-org configs don't have to rename."""
    from app.core import config as cfg_mod

    cfg_mod.reset_settings_for_tests()
    monkeypatch.delenv("SONAR_ORG", raising=False)
    monkeypatch.setenv("SONAR_ORGS", "exampleorg,exampledivision")
    settings = cfg_mod.get_settings()
    assert settings.sonar_orgs == ["exampleorg", "exampledivision"]

    cfg_mod.reset_settings_for_tests()


def test_run_polls_every_listed_org_once(monkeypatch, tmp_path) -> None:
    """Multi-org happy path: `run()` fetches each org separately but combines
    them into a SINGLE snapshot envelope with one poll_id. Each issue carries
    its org in `__org__` so the mapper resolves native_ids and overrides per-org.
    Verified via the in-memory adapters (fs raw_store + http transport stub)
    so we don't hit the network."""
    from app.core import config as cfg_mod
    from app.pollers import sonarcloud as poller_mod

    cfg_mod.reset_settings_for_tests()
    monkeypatch.setenv("SONAR_ORGS", "exampleorg,exampledivision")
    monkeypatch.setenv("SONAR_TOKEN", "test-token")
    monkeypatch.setenv("RAW_STORE", "fs")
    monkeypatch.setenv("RAW_STORE_FS_ROOT", str(tmp_path / "raw"))
    monkeypatch.setenv("INGEST_TRANSPORT", "http")
    monkeypatch.setenv("NORMALIZER_URL", "http://localhost:9999")

    published: list[tuple[str, str]] = []

    class _FakeTransport:
        def publish(self, source, poll_id, raw_uri):
            published.append((source, raw_uri))

    # Patch at the *call site* — the poller did `from … import build_ingest_transport`
    # so monkeypatching the source module is a no-op for the already-imported ref.
    monkeypatch.setattr(
        poller_mod, "build_ingest_transport", lambda _settings: _FakeTransport()
    )

    fetched_orgs: list[str] = []

    def _fake_fetch(*, base_url, organization, token, client_factory=None):
        fetched_orgs.append(organization)
        return [
            {
                "key": f"AY-{organization}-1",
                "project": f"{organization}_demo",
                "severity": "BLOCKER",
                "message": "demo",
            }
        ]

    monkeypatch.setattr(poller_mod, "_fetch_all_issues", _fake_fetch)

    rc = poller_mod.run()

    assert rc == 0
    assert fetched_orgs == ["exampleorg", "exampledivision"]
    assert len(published) == 1  # one combined envelope for all orgs (prevents cross-org auto-close)

    # One combined raw payload; each issue carries __org__ so the mapper resolves
    # native_ids and per-org overrides correctly.
    fs_root = tmp_path / "raw"
    payloads = list(fs_root.glob("**/*.json"))
    assert len(payloads) == 1
    body = json.loads(payloads[0].read_text())
    assert body["organization"] == ""  # combined envelope signals multi-org
    issue_orgs = {i["__org__"] for i in body["issues"]}
    assert issue_orgs == {"exampleorg", "exampledivision"}

    cfg_mod.reset_settings_for_tests()
