"""Executive view — open crit/high counts must reconcile across all sections."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.enums import Severity
from app.core.models import Finding
from tests._factory import make_finding
from tests.exec_metrics_alignment import (
    assert_exec_metrics_aligned,
    exec_scope_query,
    fetch_exec_metrics_bundle,
)

EXEC = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}

# Minimal Product exec rollup: app teams + platform teams that carry Wiz noise.
Product_EXEC_TEAMS = (
    "order",
    "offer",
    "product-platform",
    "platform-retail",
)


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


def _set_wiz_category(session, native_id: str, category: str) -> None:
    session.query(Finding).filter_by(native_id=native_id).one().wiz_category = category


def _seed_product_exec_findings(session) -> None:
    """Mixed app + platform findings; platform Wiz cloud rows must be excluded on /executive."""
    make_finding(
        session,
        native_id="ExampleOrg/order-api#crit",
        source="sonarcloud",
        severity=Severity.critical,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/offer-api#high",
        source="dependabot",
        severity=Severity.high,
        owner_team="offer",
    )

    make_finding(
        session,
        native_id="wiz:pe-issue",
        source="wiz",
        severity=Severity.critical,
        owner_team="product-platform",
        asset_id="cloudres:pe-issue",
    )
    session.flush()
    _set_wiz_category(session, "wiz:pe-issue", "issue")

    make_finding(
        session,
        native_id="wiz:pe-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="product-platform",
        asset_id="cloudres:pe-cfg",
    )
    session.flush()
    _set_wiz_category(session, "wiz:pe-cfg", "cloud_config")

    make_finding(
        session,
        native_id="wiz:pe-vuln",
        source="wiz",
        severity=Severity.high,
        owner_team="product-platform",
        asset_id="cloudres:pe-vuln",
    )
    session.flush()
    _set_wiz_category(session, "wiz:pe-vuln", "vulnerability")

    make_finding(
        session,
        native_id="wiz:retail-issue",
        source="wiz",
        severity=Severity.high,
        owner_team="platform-retail",
        asset_id="cloudres:retail-issue",
    )
    session.flush()
    _set_wiz_category(session, "wiz:retail-issue", "issue")

    make_finding(
        session,
        native_id="wiz:retail-cfg",
        source="wiz",
        severity=Severity.high,
        owner_team="platform-retail",
        asset_id="cloudres:retail-cfg",
    )
    session.flush()
    _set_wiz_category(session, "wiz:retail-cfg", "cloud_config")

    # App-team Wiz rows count every category even with platform_wiz_issues_only.
    make_finding(
        session,
        native_id="wiz:order-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
        asset_id="cloudres:order-cfg",
    )
    session.flush()
    _set_wiz_category(session, "wiz:order-cfg", "cloud_config")

    session.commit()


def test_exec_product_scope_metrics_aligned_with_platform_wiz_issues_only(
    session, client
) -> None:
    """Pillar badge, KPI strip, burn-down buckets, trend, and offender list agree."""
    _seed_product_exec_findings(session)
    qs = exec_scope_query(*Product_EXEC_TEAMS, platform_wiz_issues_only=True)

    bundle = fetch_exec_metrics_bundle(client, qs, trend_days=7, headers=EXEC)

    assert bundle["posture"]["open_criticals"] == 3
    assert bundle["posture"]["open_highs"] == 2
    assert_exec_metrics_aligned(bundle)


def test_exec_product_scope_metrics_aligned_across_duplicate_fetches(session, client) -> None:
    """Rollup + detail panels use the same scope — repeated fetches must match."""
    _seed_product_exec_findings(session)
    qs = exec_scope_query(*Product_EXEC_TEAMS, platform_wiz_issues_only=True)

    rollup_posture = client.get(
        f"/metrics/security-posture?{qs}", headers=EXEC
    ).json()
    detail = fetch_exec_metrics_bundle(client, qs, trend_days=90, headers=EXEC)

    assert detail["posture"]["open_criticals"] == rollup_posture["open_criticals"]
    assert detail["posture"]["open_highs"] == rollup_posture["open_highs"]
    assert_exec_metrics_aligned(detail)


def test_exec_sections_diverge_when_posture_omits_platform_wiz_issues_only(
    session, client
) -> None:
    """Regression guard: exec must pass platform_wiz_issues_only to every endpoint."""
    _seed_product_exec_findings(session)
    teams_qs = exec_scope_query(*Product_EXEC_TEAMS, platform_wiz_issues_only=False)

    posture = client.get(
        f"/metrics/security-posture?{teams_qs}", headers=EXEC
    ).json()
    bundle = fetch_exec_metrics_bundle(
        client,
        f"{teams_qs}&platform_wiz_issues_only=true",
        trend_days=7,
        headers=EXEC,
    )

    assert posture["open_highs"] == 4
    assert bundle["posture"]["open_highs"] == 2
    assert posture["open_highs"] != bundle["posture"]["open_highs"]
    assert_exec_metrics_aligned(bundle)
