"""Scope resolver uses Component Registry for application / executive pillar."""

from __future__ import annotations

from pathlib import Path

from app.core.component_registry import parse_component_registry
from app.core.config_store import OwnershipMap, ScopeMap, _parse_ownership
from app.core.scope_resolver import resolve_scope

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ownership() -> OwnershipMap:
    text = (REPO_ROOT / "config/ownership.yaml").read_text(encoding="utf-8")
    return _parse_ownership(text)


def _registry():
    text = (REPO_ROOT / "config/component_registry.yaml").read_text(encoding="utf-8")
    return parse_component_registry(text)


def test_application_scope_uses_registry_repos() -> None:
    ownership = _ownership()
    registry = _registry()
    scope = resolve_scope(
        ownership=ownership,
        scope_map=ScopeMap(),
        registry=registry,
        application="commerce",
    )
    assert {"storefront", "orders"}.issubset(scope.teams)
    assert scope.repo_asset_ids
    assert any("orders-api" in aid for aid in scope.repo_asset_ids)


def test_executive_pillar_from_registry() -> None:
    ownership = _ownership()
    registry = _registry()
    scope = resolve_scope(
        ownership=ownership,
        scope_map=ScopeMap(),
        registry=registry,
        executive_pillar="product",
    )
    assert scope.teams == ("storefront", "orders", "product-platform")
