"""Wiz portal URL builder."""

from __future__ import annotations

from app.core.wiz_portal import resolve_wiz_upstream_url, wiz_portal_url


def test_wiz_portal_issue_hash_url(monkeypatch) -> None:
    monkeypatch.delenv("WIZ_PORTAL_BASE_URL", raising=False)
    url = wiz_portal_url("wiz:abc-123", "issue")
    assert url == "https://app.wiz.io/issues#~(issue~'abc-123)"


def test_wiz_portal_vulnerability_without_portal_url_returns_none() -> None:
    assert wiz_portal_url("wiz:abc-123", "vulnerability") is None


def test_wiz_portal_cloud_config_hash_url(monkeypatch) -> None:
    monkeypatch.delenv("WIZ_PORTAL_BASE_URL", raising=False)
    url = wiz_portal_url("wiz:cfg-abc-123", "cloud_config")
    assert url == (
        "https://app.wiz.io/findings/configuration-findings/cloud"
        "#~(entity~(~'cfg-abc-123*2cCONFIGURATION_FINDING))"
    )


def test_wiz_portal_ignores_regional_api_host(monkeypatch) -> None:
    monkeypatch.setenv("WIZ_API_URL", "https://api.eu26.app.wiz.io/graphql")
    url = wiz_portal_url("wiz:issue-1", "issue")
    assert url == "https://app.wiz.io/issues#~(issue~'issue-1)"
    assert "eu26" not in url


def test_resolve_wiz_upstream_url_prefers_portal_url() -> None:
    url = resolve_wiz_upstream_url(
        {
            "portalUrl": (
                "https://app.wiz.io/explorer/vulnerability-findings"
                "#~(entity~(~'abc*2cSECURITY_TOOL_FINDING))"
            )
        },
        native_id="wiz:abc",
        wiz_category="vulnerability",
    )
    assert url is not None
    assert url.startswith("https://app.wiz.io/explorer/")


def test_wiz_portal_url_invalid_returns_none() -> None:
    assert wiz_portal_url("dependabot:1", "vulnerability") is None
    assert wiz_portal_url("wiz:1", None) is None


def test_wiz_portal_threat_center_url() -> None:
    url = wiz_portal_url("wiz:threat:wiz-adv-2026-094", "threat_center")
    assert url == "https://app.wiz.io/boards/threat-center/wiz-adv-2026-094"
