"""Wiz subscription → platform pillar mapping."""

from __future__ import annotations

from pathlib import Path

from app.core.wiz_subscription_pillar import (
    apply_platform_pillar_tags,
    owner_team_for_wiz_platform_tags,
    parse_wiz_subscription_pillar,
    platform_pillar_tag,
    subscription_fields_from_node,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PILLAR_YAML = REPO_ROOT / "config/wiz_subscription_pillar.yaml"


def test_parse_production_yaml() -> None:
    m = parse_wiz_subscription_pillar(PILLAR_YAML.read_text(encoding="utf-8"))
    assert m.by_external_id["example-product-prod"] == "product"


def test_resolve_name_pattern_suffix() -> None:
    m = parse_wiz_subscription_pillar(
        """
version: 1
name_patterns:
  - pattern: "-product"
    pillar: product
subscriptions: []
"""
    )
    assert m.resolve(external_id="example-product-services") == "product"


def test_apply_platform_pillar_tags_replaces_stale_tag() -> None:
    m = parse_wiz_subscription_pillar(
        """
version: 1
subscriptions:
  - external_id: acct-1
    pillar: io
"""
    )
    tags = apply_platform_pillar_tags(
        ["wiz_category:issue", "platform_pillar:product", "cloud_account:acct-1"],
        pillar_map=m,
        external_id="acct-1",
        name=None,
    )
    assert platform_pillar_tag("io") in tags
    assert platform_pillar_tag("product") not in tags


def test_owner_team_for_wiz_platform_tags(monkeypatch) -> None:
    class Registry:
        def teams_for_executive_pillar(self, pillar: str) -> tuple[str, ...]:
            return {
                "product": ("storefront", "product-platform"),
                "retail": ("retail", "platform-retail"),
            }.get(pillar, ())

    class Cache:
        def get_component_registry(self) -> Registry:
            return Registry()

    monkeypatch.setattr("app.core.config_store.get_config_cache", lambda: Cache())
    assert owner_team_for_wiz_platform_tags(["platform_pillar:product"]) == "product-platform"
    assert owner_team_for_wiz_platform_tags(["platform_pillar:retail"]) == "platform-retail"
    assert owner_team_for_wiz_platform_tags(["platform_pillar:threat-intel"]) is None
    assert owner_team_for_wiz_platform_tags(["cloud_account:foo"]) is None


def test_subscription_fields_from_vuln_node() -> None:
    ext, name = subscription_fields_from_node(
        {
            "vulnerableAsset": {
                "subscriptionExternalId": "example-production-project",
                "subscriptionName": "example-production-app",
            }
        }
    )
    assert ext == "example-production-project"
    assert name == "example-production-app"


def test_mapper_tags_include_platform_pillar(monkeypatch) -> None:
    from app.core.config_store import reset_config_cache_for_tests
    from app.normalizer.mappers.wiz import map_node

    reset_config_cache_for_tests()
    pillar_map = parse_wiz_subscription_pillar(
        """
version: 1
subscriptions:
  - external_id: "111"
    pillar: retail
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
            "id": "vuln-1",
            "vendorSeverity": "CRITICAL",
            "vulnerableAsset": {"subscriptionExternalId": "111", "name": "vm"},
        },
        "vulnerability",
    )
    assert platform_pillar_tag("retail") in nf.tags


def test_custom_pillar_is_supported() -> None:
    mapping = parse_wiz_subscription_pillar(
        """
version: 1
subscriptions:
  - external_id: x
    pillar: custom-product
"""
    )
    assert mapping.resolve(external_id="x") == "custom-product"
