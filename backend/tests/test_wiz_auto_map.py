"""Wiz auto-map matchers (offline)."""

from __future__ import annotations

from app.core.wiz_auto_map import (
    RegistryComponent,
    _score_candidate,
    build_suggestions,
    load_registry_components,
    load_suggestions_from_yaml,
    match_slug,
    normalize_slug,
    parse_unmapped_catalog_entry,
    resolve_manual_target,
)
from app.core.wiz_catalog import WizCatalogService


def test_parse_unmapped_catalog_entry() -> None:
    assert parse_unmapped_catalog_entry("- payment-cache-api - merchandising") == (
        "payment-cache-api",
        "merchandising",
    )
    assert parse_unmapped_catalog_entry("- event-exporter") is None


def test_resolve_manual_component() -> None:
    components = [
        RegistryComponent(
            key="catalog-api",
            label="Catalog API",
            repo="catalog-api",
            teams=("merchandising",),
            dev_pillar="retail",
            wiz_service=None,
        ),
    ]
    resolved = resolve_manual_target(
        "payment-cache-api",
        "merchandising",
        components,
        taken_components=set(),
    )
    assert resolved == ("catalog-api", "merchandising")


def test_operator_manual_from_suggestions() -> None:
    from app.core.wiz_auto_map import operator_manual_from_suggestions

    raw = {
        "suggestions": [
            {"wiz_service": "pricing-api", "component_key": "", "team": "product-platform"},
            {"wiz_service": "telemetry", "component_key": "platform-observability", "team": "product-platform"},
        ]
    }
    manual = operator_manual_from_suggestions(raw)
    assert len(manual) == 1
    assert manual[0]["wiz_service"] == "pricing-api"
    assert manual[0]["team"] == "product-platform"


def test_load_suggestions_includes_annotated_unmapped(tmp_path) -> None:
    path = tmp_path / "suggested.yaml"
    path.write_text(
        "suggestions: []\nunmapped_catalog:\n- offer-feed-consumer - offers\n",
        encoding="utf-8",
    )
    from app.core.config_validate import default_paths

    suggestions, team_only = load_suggestions_from_yaml(
        path, config_dir=default_paths()[0]
    )
    assert any(s.wiz_service == "offer-feed-consumer" for s in suggestions) or (
        "offer-feed-consumer" in team_only
    )


def test_normalize_slug_is_tenant_agnostic() -> None:
    assert normalize_slug("Orders API") == "orders-api"
    assert normalize_slug("tenant-orders-api") == "tenant-orders-api"


def test_match_exact_normalized_component() -> None:
    components = [
        RegistryComponent(
            key="orders-api",
            label="Orders API",
            repo="orders-api",
            teams=("orders",),
            dev_pillar="product",
            wiz_service=None,
        ),
    ]
    by_key = {"orders-api": components[0]}
    sug = match_slug(
        "orders-api",
        components=components,
        overrides={},
        by_key=by_key,
        catalog_by_name={
            "orders-api": WizCatalogService("orders-api", ("Product",))
        },
        finding_counts={"orders-api": 5},
    )
    assert sug is not None
    assert sug.component_key == "orders-api"
    assert sug.team == "orders"
    assert sug.matcher == "exact_normalized"


def test_unrelated_repo_does_not_match_pricing_api() -> None:
    catalog = RegistryComponent(
        key="catalog-api",
        label="Catalog API",
        repo="catalog-api",
        teams=("merchandising",),
        dev_pillar="retail",
        wiz_service=None,
    )
    score, matcher = _score_candidate(
        normalize_slug("pricing-api"),
        catalog,
    )
    assert score == 0.0 or matcher != "repo_norm"


def test_override_wins() -> None:
    components = [
        RegistryComponent(
            key="ordercore",
            label="OrderCore",
            repo="order-engine",
            teams=("order",),
            dev_pillar="product",
            wiz_service=None,
        ),
    ]
    sug = match_slug(
        "weird-wiz-name",
        components=components,
        overrides={"weird-wiz-name": "ordercore"},
        by_key={"ordercore": components[0]},
        catalog_by_name={},
        finding_counts={},
    )
    assert sug is not None
    assert sug.matcher == "override"
    assert sug.confidence == "high"


def test_otel_slug_does_not_match_taxengine_stack() -> None:
    components = [
        RegistryComponent(
            key="taxengine-stack",
            label="TaxEngine Stack",
            repo="tax-engine",
            teams=("tax",),
            dev_pillar="product",
            wiz_service=None,
        ),
    ]
    sug = match_slug(
        "otel-stack-agent-collector",
        components=components,
        overrides={},
        by_key={"taxengine-stack": components[0]},
        catalog_by_name={},
        finding_counts={},
    )
    assert sug is None or sug.component_key != "taxengine-stack"


def test_build_suggestions_greedy_one_component() -> None:
    components = [
        RegistryComponent(
            key="offerengine",
            label="OfferEngine",
            repo="offer-engine",
            teams=("offer",),
            dev_pillar="product",
            wiz_service=None,
        ),
    ]
    catalog = [
        WizCatalogService("offers-api", ("Product",)),
        WizCatalogService("offerengine", ("Product",)),
        WizCatalogService("offer-feed-consumer", ("Product",)),
    ]
    report = build_suggestions(
        catalog=catalog,
        components=components,
        overrides={},
        finding_counts={
            "offers-api": 5,
            "offerengine": 10,
            "offer-feed-consumer": 3,
        },
    )
    offer_suggestions = [s for s in report.suggestions if s.component_key == "offerengine"]
    assert len(offer_suggestions) == 1
    assert offer_suggestions[0].wiz_service == "offerengine"
    assert "offers-api" in report.unmapped_catalog


def test_build_suggestions_skips_unknown() -> None:
    components = [
        RegistryComponent(
            key="x",
            label="X",
            repo="example-x",
            teams=("order",),
            dev_pillar="product",
            wiz_service=None,
        ),
    ]
    report = build_suggestions(
        catalog=[],
        components=components,
        overrides={},
        finding_counts={"unknown": 100, "order-engine": 2},
    )
    assert not any(s.wiz_service == "unknown" for s in report.suggestions)
    assert any(s == "unknown" and n == 100 for s, n in report.unmapped_findings_only)


def test_registry_fixture_has_no_duplicate_wiz_when_clean() -> None:
    from app.core.config_validate import default_paths

    config_dir, _ = default_paths()
    rows = load_registry_components(config_dir)
    wiz = [c.wiz_service for c in rows if c.wiz_service]
    assert len(wiz) == len(set(wiz))
