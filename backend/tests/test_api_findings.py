"""`/findings` listing + filtering tests under the single-`is_admin` model.

Authorization collapsed to a single per-email flag. The role-shaped tests that used to live here
(`developer sees only their team`, `admin browsing /developer is bounded by
view scope`, `developer_cannot_request_admin_role`, etc.) have been removed
because the contract they pinned no longer exists: any IAP-authenticated
user gets full data on every non-`/admin` surface, and pages narrow
themselves with `?team=` / `?source=`. What remains worth pinning is the
admin-only-source gating (Trivy-in-SonarCloud) and the structural filter +
sort + pagination behaviour.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.main import create_app
from app.core.enums import Severity, Status
from tests._factory import make_finding


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


# Identity helpers — `_hdr()` is the non-admin caller (`dev1@example.com`,
# not in `rbac.yaml.admin_emails`). `_admin_hdr()` is the admin caller
# (`admin1@example.com`, the email listed in the test fixture). Groups are
# kept around because IAP injects them; the backend ignores them today.
def _hdr(email: str = "dev1@example.com", groups: list[str] | None = None) -> dict[str, str]:
    return {
        "X-Dev-Identity": json.dumps(
            {"email": email, "google.groups": groups or ["engineering@example.com"]}
        )
    }


def _admin_hdr() -> dict[str, str]:
    return _hdr("admin1@example.com")


def _seed(session) -> None:
    make_finding(session, native_id="ExampleOrg/example-service#1", owner_team="pricing-platform")
    make_finding(session, native_id="ExampleOrg/another-service#2", owner_team="data-platform")
    make_finding(session, native_id="ExampleOrg/wild-thing#3", owner_team="unowned")
    session.commit()
    session.execute(text("SELECT 1"))  # ensure flush


def test_authenticated_user_sees_every_team(client, session) -> None:
    """Any IAP-authenticated caller sees the full org-wide listing across
    every team (including `unowned`). Pre-amendment this was three separate
    tests pinning developer / executive / admin scopes — they all collapse
    to the same expectation now."""
    _seed(session)
    r = client.get("/findings", headers=_hdr())
    assert r.status_code == 200
    teams = {i["owner_team"] for i in r.json()["items"]}
    assert teams == {"pricing-platform", "data-platform", "unowned"}


def test_admin_caller_also_sees_every_team(client, session) -> None:
    """Same expectation for an admin caller — admin doesn't broaden the
    default listing, it only unlocks the `/admin` page surfaces and the
    `?source=sonarcloud_trivy` opt-in."""
    _seed(session)
    r = client.get("/findings", headers=_admin_hdr())
    assert r.status_code == 200
    teams = {i["owner_team"] for i in r.json()["items"]}
    assert teams == {"pricing-platform", "data-platform", "unowned"}


def test_team_query_param_narrows_listing(client, session) -> None:
    """Narrowing is now purely via `?team=`. Confirms a non-admin can ask
    for a single team's findings and get just that team."""
    _seed(session)
    r = client.get("/findings?team=pricing-platform", headers=_hdr())
    assert r.status_code == 200
    teams = {i["owner_team"] for i in r.json()["items"]}
    assert teams == {"pricing-platform"}


def test_executive_pillar_filter_narrows_listing(client, session) -> None:
    _seed(session)
    r = client.get("/findings?executive_pillar=product", headers=_hdr())
    assert r.status_code == 200
    teams = {i["owner_team"] for i in r.json()["items"]}
    assert teams == {"pricing-platform", "data-platform"}


def test_application_filter_narrows_listing(client, session) -> None:
    _seed(session)
    r = client.get("/findings?application=pricing-app", headers=_hdr())
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["owner_team"] == "pricing-platform"


def test_service_and_server_filters_narrow_listing(client, session) -> None:
    _seed(session)
    by_service = client.get("/findings?service=pricing-service", headers=_hdr())
    assert by_service.status_code == 200
    assert {i["owner_team"] for i in by_service.json()["items"]} == {"pricing-platform"}

    by_server = client.get("/findings?server=pricing-service", headers=_hdr())
    assert by_server.status_code == 200
    assert {i["owner_team"] for i in by_server.json()["items"]} == {"pricing-platform"}


def test_repo_filter_accepts_org_repo_and_bare_repo(client, session) -> None:
    _seed(session)
    full = client.get("/findings?repo=ExampleOrg/example-service", headers=_hdr())
    assert full.status_code == 200
    assert full.json()["total"] == 1

    bare = client.get("/findings?repo=example-service", headers=_hdr())
    assert bare.status_code == 200
    assert bare.json()["total"] == 1


def test_list_findings_excludes_auto_closed_by_default(client, session) -> None:
    make_finding(session, native_id="ExampleOrg/example-service#open", severity=Severity.critical)
    make_finding(
        session,
        native_id="ExampleOrg/example-service#closed",
        severity=Severity.critical,
        status=Status.auto_closed,
    )
    session.commit()

    r = client.get("/findings?severity=critical", headers=_hdr())
    assert r.status_code == 200
    native_ids = {i["native_id"] for i in r.json()["items"]}
    assert "ExampleOrg/example-service#open" in native_ids
    assert "ExampleOrg/example-service#closed" not in native_ids


def test_filter_by_severity_and_status(client, session) -> None:
    make_finding(session, native_id="ExampleOrg/example-service#1", severity=Severity.critical)
    make_finding(session, native_id="ExampleOrg/example-service#2", severity=Severity.low)
    make_finding(
        session,
        native_id="ExampleOrg/example-service#3",
        severity=Severity.critical,
        status=Status.auto_closed,
    )
    session.commit()

    r = client.get("/findings?severity=critical&status=open", headers=_hdr())
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["severity"] == "critical"
    assert items[0]["status"] == "open"


def test_finding_detail_includes_event_timeline(client, session) -> None:
    make_finding(
        session,
        native_id="ExampleOrg/example-service#5",
        status=Status.auto_closed,
    )
    session.commit()

    r_list = client.get("/findings?status=auto_closed", headers=_hdr())
    assert r_list.status_code == 200
    fid = r_list.json()["items"][0]["id"]

    r = client.get(f"/findings/{fid}", headers=_hdr())
    assert r.status_code == 200
    body = r.json()
    event_types = [e["event_type"] for e in body["events"]]
    assert "discovered" in event_types
    assert "auto_closed" in event_types
    assert body["consecutive_misses"] == 0


def test_finding_detail_404_for_unknown_id(client, session) -> None:
    """Bogus UUID → 404. The previous "out of scope" 404 path no longer
    exists (every authenticated user can see every team's findings); the
    only remaining 404 case is "no such finding" plus the admin-only-source
    detail miss covered in the trivy tests below."""
    _seed(session)
    r = client.get(
        "/findings/00000000-0000-0000-0000-000000000000",
        headers=_hdr(),
    )
    assert r.status_code == 404


# ---------------- filters ----------------


def _seed_for_filters(session) -> None:
    """Diverse population for filter / sort tests. Every authenticated user
    sees them all (no team scoping); `?team=`/`?asset=` narrowing happens
    via query params from the calling page."""
    make_finding(
        session,
        native_id="ExampleOrg/example-service#10",
        title="OpenSSL CVE in transitive dep",
        severity=Severity.critical,
        upstream_age_days=20,  # breached (critical SLA = 7d)
    )
    make_finding(
        session,
        native_id="ExampleOrg/example-service#11",
        title="Lodash prototype pollution",
        severity=Severity.high,
        upstream_age_days=2,  # ok (high SLA = 30d)
    )
    make_finding(
        session,
        native_id="ExampleOrg/example-service#12",
        title="Unused asset finding",
        severity=Severity.low,
        upstream_age_days=200,  # breached (low SLA = 180d)
    )
    session.commit()


def test_filter_by_multiple_severities(client, session) -> None:
    """`?severity=critical&severity=high` returns the union; medium/low/info excluded."""
    _seed_for_filters(session)
    r = client.get("/findings?severity=critical&severity=high", headers=_hdr())
    body = r.json()
    severities = {i["severity"] for i in body["items"]}
    assert severities == {"critical", "high"}
    assert body["total"] == 2


def test_filter_by_multiple_sources(client, session) -> None:
    """`?source=dependabot&source=sonarcloud` union semantics (Platform Product tab)."""
    make_finding(
        session,
        native_id="dep#1",
        source="dependabot",
        owner_team="product-platform",
    )
    make_finding(
        session,
        native_id="son#1",
        source="sonarcloud",
        owner_team="product-platform",
    )
    make_finding(
        session,
        native_id="wiz#1",
        source="wiz",
        owner_team="product-platform",
    )
    session.commit()
    r = client.get(
        "/findings?team=product-platform&source=dependabot&source=sonarcloud",
        headers=_hdr(),
    )
    body = r.json()
    assert body["total"] == 2
    assert {i["source"] for i in body["items"]} == {"dependabot", "sonarcloud"}


def test_filter_by_title_substring(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?title=lodash", headers=_hdr())
    body = r.json()
    assert body["total"] == 1
    assert "Lodash" in body["items"][0]["title"]


def test_filter_by_asset_substring(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?asset=example-service", headers=_hdr())
    body = r.json()
    assert body["total"] == 3


def test_filter_sla_breached_pushed_to_sql(client, session) -> None:
    """Critical (20d > 7d) and low (200d > 180d) breach; high (2d) does not.

    The filter must be applied before pagination so `total` is correct.
    """
    _seed_for_filters(session)
    r = client.get("/findings?sla_breached=true", headers=_hdr())
    body = r.json()
    assert body["total"] == 2
    severities = {i["severity"] for i in body["items"]}
    assert severities == {"critical", "low"}

    r2 = client.get("/findings?sla_breached=false", headers=_hdr())
    body2 = r2.json()
    assert body2["total"] == 1
    assert body2["items"][0]["severity"] == "high"


# ---------------- sort ----------------


def test_sort_by_severity_default_critical_first(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings", headers=_hdr())
    items = r.json()["items"]
    assert [i["severity"] for i in items] == ["critical", "high", "low"]


def test_sort_by_age_desc_oldest_first(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?sort_by=age&sort_dir=desc", headers=_hdr())
    ages = [i["age_days"] for i in r.json()["items"]]
    assert ages == sorted(ages, reverse=True)


def test_sort_by_age_asc_newest_first(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?sort_by=age&sort_dir=asc", headers=_hdr())
    ages = [i["age_days"] for i in r.json()["items"]]
    assert ages == sorted(ages)


def test_sort_by_title_alphabetical(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?sort_by=title", headers=_hdr())
    titles = [i["title"] for i in r.json()["items"]]
    assert titles == sorted(titles, key=str.lower)


def test_sort_rejects_unknown_key(client, session) -> None:
    _seed_for_filters(session)
    r = client.get("/findings?sort_by=nonsense", headers=_hdr())
    assert r.status_code == 422


# ---------------- admin-only sources (sonarcloud_trivy) ----------------
#
# SonarCloud lets teams import third-party scanner reports as "external
# issues"; some Sonar projects carry Trivy CVE entries that surface on the
# same `/api/issues/search` response as native Sonar rule violations. The
# mapper splits those into `Finding.source = "sonarcloud_trivy"` and the
# scoping layer hides that source from every surface by default. The /admin
# page surfaces them via a dedicated section that opts back in by passing
# `?source=sonarcloud_trivy` on the wire — gated to admin on the request
# side so a misconfigured non-admin client fails loudly.


def _seed_with_trivy(session) -> None:
    """Mixed population covering the matrix:
    - native Sonar on pricing-platform (visible to everyone)
    - Trivy-in-Sonar on pricing-platform (must NOT be visible by default
      despite the team match — the source-level exclusion is what's being
      pinned, separate from team scoping)
    - Trivy-in-Sonar on data-platform and unowned (visible only via the
      admin explicit-source opt-in).
    """
    make_finding(
        session,
        source="sonarcloud",
        native_id="exampleorg/exampleorg_product-core#native-1",
        owner_team="pricing-platform",
        title="Native Sonar rule",
    )
    make_finding(
        session,
        source="sonarcloud_trivy",
        native_id="exampleorg/exampleorg_product-core#trivy-on-pricing",
        owner_team="pricing-platform",
        title="External Trivy CVE on pricing-platform asset",
    )
    make_finding(
        session,
        source="sonarcloud_trivy",
        native_id="exampleorg/exampleorg_product-core#trivy-on-data",
        owner_team="data-platform",
        title="External Trivy CVE on data-platform asset",
    )
    make_finding(
        session,
        source="sonarcloud_trivy",
        native_id="exampleorg/exampleorg_product-core#trivy-unowned",
        owner_team="unowned",
        title="External Trivy on unowned asset",
    )
    session.commit()


def test_non_admin_default_listing_excludes_sonarcloud_trivy(client, session) -> None:
    """The customer requirement: Trivy-in-SonarCloud findings must not
    appear anywhere a non-admin browses (every page they reach is
    structurally non-admin)."""
    _seed_with_trivy(session)
    r = client.get("/findings", headers=_hdr())
    assert r.status_code == 200
    sources = {i["source"] for i in r.json()["items"]}
    assert "sonarcloud_trivy" not in sources


def test_admin_default_listing_also_excludes_sonarcloud_trivy(client, session) -> None:
    """The post-2026-05-19 opt-in policy: even an admin browsing
    `/findings` without an explicit `?source=` does NOT see Trivy-in-Sonar.
    The /admin page's existing Unowned and Outside-dev-view sections must
    not double-count those findings. Trivy-in-Sonar surfaces only via the
    dedicated `?source=sonarcloud_trivy` opt-in path."""
    _seed_with_trivy(session)
    r = client.get("/findings", headers=_admin_hdr())
    assert r.status_code == 200
    sources = {i["source"] for i in r.json()["items"]}
    assert "sonarcloud_trivy" not in sources


def test_admin_can_fetch_sonarcloud_trivy_via_explicit_source(client, session) -> None:
    """The dedicated `/admin` "Trivy issues in SonarCloud" section calls
    `/findings?source=sonarcloud_trivy`. Pinning that admins can read every
    such finding regardless of owner_team (assigned and unowned)."""
    _seed_with_trivy(session)
    r = client.get("/findings?source=sonarcloud_trivy", headers=_admin_hdr())
    assert r.status_code == 200
    items = r.json()["items"]
    assert {i["source"] for i in items} == {"sonarcloud_trivy"}
    assert {i["owner_team"] for i in items} == {
        "pricing-platform",
        "data-platform",
        "unowned",
    }


def test_non_admin_explicit_sonarcloud_trivy_is_forbidden(client, session) -> None:
    """A non-admin can't bypass the source split by asking for it directly —
    non-admin requests for an admin-only source return 403 (loud failure)
    rather than a silent empty list, so a misconfigured client surfaces the
    privilege issue in logs instead of looking like "no findings to triage"."""
    _seed_with_trivy(session)
    r = client.get("/findings?source=sonarcloud_trivy", headers=_hdr())
    assert r.status_code == 403


def test_metrics_security_posture_unowned_excludes_sonarcloud_trivy(
    client, session
) -> None:
    """The /admin Unowned KPI strip (which calls
    `/metrics/security-posture?team=unowned`) must NOT include the
    Trivy-on-unowned row in its open_criticals / open_highs counts.
    Otherwise the headline number on /admin would jump every time a Sonar
    project ingests a new external Trivy CVE — exactly what the customer
    asked us to avoid."""
    make_finding(
        session,
        source="sonarcloud",
        native_id="exampleorg/x#sonar-unowned",
        owner_team="unowned",
        severity=Severity.high,
    )
    make_finding(
        session,
        source="sonarcloud_trivy",
        native_id="exampleorg/x#trivy-unowned",
        owner_team="unowned",
        severity=Severity.critical,
    )
    session.commit()

    r = client.get("/metrics/security-posture?team=unowned", headers=_admin_hdr())
    assert r.status_code == 200
    body = r.json()
    # The single critical in the seeded data is Trivy-in-Sonar; it must be
    # excluded. The single high (native Sonar) must remain.
    assert body["open_criticals"] == 0
    assert body["open_highs"] == 1
    assert body["sonarcloud"]["highs"] == 1
    assert body["sonarcloud"]["criticals"] == 0


def test_admin_triage_unowned_excludes_platform_wiz(client, session) -> None:
    """Unowned Wiz stamped to a platform pillar tab must not duplicate on /admin."""
    orphan = make_finding(
        session,
        source="wiz",
        native_id="wiz-orphan#1",
        owner_team="unowned",
        asset_id="cloudres:gcp/123/vm-1",
        tags=["platform_pillar:product"],
    )
    orphan.wiz_category = "cloud_config"
    make_finding(
        session,
        source="dependabot",
        native_id="ExampleOrg/no-map#1",
        owner_team="unowned",
        asset_id="repo:ExampleOrg/no-map",
    )
    session.commit()

    r = client.get("/findings?team=unowned", headers=_admin_hdr())
    assert r.status_code == 200
    native_ids = {i["native_id"] for i in r.json()["items"]}
    assert "wiz-orphan#1" not in native_ids
    assert "ExampleOrg/no-map#1" in native_ids


def test_admin_triage_unowned_excludes_mapped_dev_assets(client, session) -> None:
    """Rows still stamped unowned but mapped in ownership.yaml belong on /developer."""
    make_finding(
        session,
        source="dependabot",
        native_id="ExampleOrg/example-service#pending",
        owner_team="unowned",
        asset_id="repo:ExampleOrg/example-service",
    )
    make_finding(
        session,
        source="dependabot",
        native_id="ExampleOrg/no-map#1",
        owner_team="unowned",
        asset_id="repo:ExampleOrg/no-map",
    )
    session.commit()

    r = client.get("/findings?team=unowned", headers=_admin_hdr())
    assert r.status_code == 200
    native_ids = {i["native_id"] for i in r.json()["items"]}
    assert "ExampleOrg/example-service#pending" not in native_ids
    assert "ExampleOrg/no-map#1" in native_ids
