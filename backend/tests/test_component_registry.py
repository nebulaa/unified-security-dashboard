"""Component Registry load, validation, and GET /components."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.component_registry import parse_component_registry
from app.core.config_store import reset_config_cache_for_tests
from app.core.config_validate import default_paths, validate_all, validate_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "config/component_registry.yaml"

HDR = {"X-Dev-Identity": json.dumps({"email": "dev1@example.com"})}


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


def test_component_registry_yaml_parses() -> None:
    reg = parse_component_registry(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert reg.version == 1
    assert len(reg.components) >= 2
    assert reg.developer_scope_team_keys
    assert reg.executive_pillars


def test_wiz_indexes_include_supplemental_map() -> None:
    from app.core.component_registry import enrich_registry_wiz_indexes
    from app.core.wiz_auto_map import load_wiz_service_team_map

    reg = parse_component_registry(REGISTRY_PATH.read_text(encoding="utf-8"))
    reg = enrich_registry_wiz_indexes(reg, load_wiz_service_team_map(REGISTRY_PATH.parent))
    assert reg.wiz_service_to_team
    assert reg.wiz_service_to_team["web-store"] == "storefront"
    assert reg.wiz_service_to_team["retail-platform"] == "platform-retail"
    assert "storefront" in reg.wiz_teams_for_pillar["product"]


def test_validate_all_passes_with_registry() -> None:
    config_dir, repo_root = default_paths()
    result = validate_all(config_dir=config_dir, repo_root=repo_root)
    assert result.ok, result.errors


def test_validate_registry_rejects_duplicate_wiz_service() -> None:
    from app.core.config_store import OwnershipMap, TeamConfig

    ownership = OwnershipMap(
        asset_to_team={"repo:ExampleOrg/product-core": "order"},
        teams={"order": TeamConfig(name="order"), "offer": TeamConfig(name="offer")},
    )
    rows = [
        {
            "key": "a",
            "label": "A",
            "application": "ndc",
            "teams": ["order"],
            "wiz_service": "same-slug",
            "repo": "product-core",
        },
        {
            "key": "b",
            "label": "B",
            "application": "ndc",
            "teams": ["offer"],
            "wiz_service": "same-slug",
            "repo": "product-core",
        },
    ]
    result = validate_registry(ownership, rows)
    assert not result.ok
    assert "duplicate wiz_service" in result.errors[0]


def test_get_components_endpoint(client) -> None:
    reset_config_cache_for_tests()
    r = client.get("/components", headers=HDR)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert len(body["components"]) >= 2
    assert body["developer_scope"]["team_keys"]
    assert "indexes" in body
    assert body["indexes"]["wiz_service_to_team"]["order-engine"] == "order"
    assert "order" in body["indexes"]["wiz_teams_for_pillar"]["product"]
