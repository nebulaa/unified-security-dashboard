"""Wiz mapper roundtrips."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid5

from app.core.config import get_settings
from app.core.enums import Severity
from app.normalizer.mappers.wiz import (
    WIZ_SOURCE,
    map_node,
    map_snapshot,
    native_id_for_node,
)


def test_native_id_is_category_free() -> None:
    node = {"id": "abc-123", "severity": "CRITICAL", "status": "OPEN"}
    assert native_id_for_node(node) == "wiz:abc-123"


def test_vulnerability_maps_portal_url() -> None:
    portal = (
        "https://app.wiz.io/explorer/vulnerability-findings"
        "#~(entity~(~'vuln-1*2cSECURITY_TOOL_FINDING))"
    )
    nf = map_node(
        {
            "id": "vuln-1",
            "status": "OPEN",
            "vendorSeverity": "CRITICAL",
            "name": "CVE-2024-0001",
            "portalUrl": portal,
            "vulnerabilityExternalId": "CVE-2024-0001",
            "firstDetectedAt": "2025-03-01T10:00:00Z",
            "hasCisaKevExploit": True,
            "vulnerableAsset": {
                "name": "vm-1",
                "cloudPlatform": "AWS",
                "subscriptionExternalId": "111",
            },
        },
        "vulnerability",
    )
    assert nf.upstream_url == portal


def test_issue_maps_hash_portal_url_when_no_portal_url_field() -> None:
    nf = map_node(
        {
            "id": "issue-1",
            "severity": "HIGH",
            "status": "OPEN",
            "createdAt": "2025-04-01T12:00:00Z",
            "applicationServices": [{"id": "svc-1", "displayName": "order-engine"}],
        },
        "issue",
    )
    assert nf.upstream_url == "https://app.wiz.io/issues#~(issue~'issue-1)"


def test_cloud_config_maps_hash_portal_url_when_no_portal_url_field() -> None:
    nf = map_node(
        {
            "id": "cfg-1",
            "severity": "HIGH",
            "status": "OPEN",
            "analyzedAt": "2025-04-01T12:00:00Z",
            "rule": {"name": "Shielded VM should be enabled"},
            "resource": {
                "name": "vm-1",
                "cloudPlatform": "GCP",
                "subscriptionExternalId": "prj-1",
            },
        },
        "cloud_config",
    )
    assert nf.upstream_url == (
        "https://app.wiz.io/findings/configuration-findings/cloud"
        "#~(entity~(~'cfg-1*2cCONFIGURATION_FINDING))"
    )


def test_vulnerability_maps_with_kev_fields() -> None:
    nf = map_node(
        {
            "id": "vuln-1",
            "status": "OPEN",
            "vendorSeverity": "CRITICAL",
            "name": "CVE-2024-0001",
            "vulnerabilityExternalId": "CVE-2024-0001",
            "firstDetectedAt": "2025-03-01T10:00:00Z",
            "hasCisaKevExploit": True,
            "vulnerableAsset": {
                "name": "vm-1",
                "cloudPlatform": "AWS",
                "subscriptionExternalId": "111",
            },
        },
        "vulnerability",
    )
    assert nf.source == WIZ_SOURCE
    assert nf.wiz_category == "vulnerability"
    assert nf.severity == Severity.critical
    assert nf.cve_id == "CVE-2024-0001"
    assert nf.asset_id == "cloudres:AWS/111/vm-1"
    assert nf.owner_team is None
    assert nf.upstream_created_at == datetime(2025, 3, 1, 10, 0, tzinfo=UTC)


def test_cloud_resource_stamps_platform_code_team_from_pillar_tag(monkeypatch) -> None:
    from app.core.config_store import reset_config_cache_for_tests
    from app.core.wiz_subscription_pillar import parse_wiz_subscription_pillar

    reset_config_cache_for_tests()
    pillar_map = parse_wiz_subscription_pillar(
        """
version: 1
subscriptions:
  - external_id: example-production-project
    pillar: product
"""
    )

    class _Cache:
        def get_wiz_subscription_pillar(self):
            return pillar_map

    monkeypatch.setattr(
        "app.normalizer.mappers.wiz.get_config_cache",
        lambda: _Cache(),
    )
    nf = map_node(
        {
            "id": "issue-cloud-1",
            "severity": "HIGH",
            "resource": {
                "subscription": {
                    "externalId": "example-production-project",
                    "cloudProvider": "GCP",
                    "name": "product-prd-product",
                },
                "id": "func-1",
                "name": "e2e-test-pubsub-message-trigger",
            },
        },
        "issue",
    )
    assert nf.asset_type == "cloud_resource"
    assert "platform_pillar:product" in nf.tags
    assert nf.owner_team == "product-platform"


def test_registered_wiz_service_asset() -> None:
    nf = map_node(
        {
            "id": "issue-1",
            "severity": "HIGH",
            "status": "OPEN",
            "createdAt": "2025-04-01T12:00:00Z",
            "applicationServices": [{"id": "svc-1", "displayName": "order-engine"}],
        },
        "issue",
    )
    assert nf.asset_id == "wizservice:order-engine"
    assert nf.asset_type == "wiz_service"


def test_unregistered_wiz_service_still_wizservice_namespace() -> None:
    nf = map_node(
        {
            "id": "issue-2",
            "severity": "HIGH",
            "applicationServices": [{"displayName": "not-in-registry"}],
        },
        "issue",
    )
    assert nf.asset_id == "wizservice:not-in-registry"


def test_map_snapshot_all_envelope_keys() -> None:
    envelope = {
        "issues": [{"id": "i1", "severity": "CRITICAL"}],
        "vulnerability_findings": [],
        "cloud_config": [],
        "secrets": [],
        "sensitive_data": [],
        "container": [],
        "code": [],
    }
    findings = map_snapshot(envelope)
    assert len(findings) == 1
    assert findings[0].wiz_category == "issue"


def test_map_threat_center_node() -> None:
    from app.normalizer.mappers.wiz import map_threat_center_node, native_id_for_threat

    nf = map_threat_center_node(
        {
            "id": "wiz-adv-2026-088",
            "title": "BadHost: Starlette Host Header Injection Leads to Authentication Bypass",
            "description": "Advisory text.",
            "publishedAt": "2026-05-27T17:00:00Z",
            "impactTotal": 50,
            "impactBreakdown": {"VULNERABILITY_FINDINGS": 50},
        }
    )
    assert native_id_for_threat({"id": "wiz-adv-2026-088"}) == "wiz:threat:wiz-adv-2026-088"
    assert nf.wiz_category == "threat_center"
    assert nf.severity == Severity.high
    assert "platform_pillar:threat-intel" in nf.tags
    assert "platform_pillar:product" not in nf.tags
    assert "Affected resources" in nf.description


def test_finding_id_stable() -> None:
    from uuid import UUID

    native = "wiz:dead-beef"
    expected = uuid5(UUID(get_settings().namespace_secdb), f"{WIZ_SOURCE}:{native}")
    nf = map_node({"id": "dead-beef", "severity": "HIGH"}, "issue")
    assert nf.id == expected
