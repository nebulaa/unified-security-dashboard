"""Metrics endpoints — summary, trend, top-teams, sla-breaches."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.enums import EventType, Severity, Status
from app.core.models import FindingEvent
from app.jobs.rollup import rollup_date
from tests._factory import make_finding


def _seed_daily_metrics_for_trend(session, *, days: int = 7) -> None:
    """Populate daily_metrics so /metrics/trend (non-asset path) has data."""
    end = date.today() - timedelta(days=1)
    for offset in range(days):
        rollup_date(session, end - timedelta(days=offset))
    session.commit()


@pytest.fixture()
def client(session) -> TestClient:
    return TestClient(create_app())


# Generic authenticated identity. Authorization collapsed to a single
# per-email admin flag (collapse): any authenticated user
# sees every team's data on /metrics, so this header is what every test
# below uses. Keep the name `EXEC` for diff-stability with the existing
# call sites; it no longer carries any role semantics.
EXEC = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


def test_summary_counts_open_criticals(session, client) -> None:
    make_finding(session, native_id="x#1", severity=Severity.critical)
    make_finding(session, native_id="x#2", severity=Severity.critical)
    make_finding(session, native_id="x#3", severity=Severity.high)  # not critical
    make_finding(
        session, native_id="x#4", severity=Severity.critical, status=Status.auto_closed
    )  # closed
    session.commit()

    r = client.get("/metrics/summary", headers=EXEC)
    assert r.status_code == 200
    body = r.json()
    assert body["open_criticals"] == 2
    assert body["scanners_active"] == 0  # no processed_payloads in this test


def test_summary_source_filter(session, client) -> None:
    make_finding(
        session,
        native_id="x#sonar",
        severity=Severity.critical,
        source="sonarcloud",
    )
    make_finding(
        session,
        native_id="x#dep",
        severity=Severity.critical,
        source="dependabot",
    )
    make_finding(
        session,
        native_id="x#trivy",
        severity=Severity.high,
        source="trivy",
    )
    session.commit()

    all_crit = client.get("/metrics/summary", headers=EXEC).json()
    assert all_crit["open_criticals"] == 2

    sonar_trivy = client.get(
        "/metrics/summary?source=sonarcloud&source=trivy",
        headers=EXEC,
    ).json()
    assert sonar_trivy["open_criticals"] == 1


def test_summary_executive_pillar_filter(session, client) -> None:
    make_finding(
        session, native_id="x#1", severity=Severity.critical, owner_team="pricing-platform"
    )
    make_finding(
        session, native_id="x#2", severity=Severity.critical, owner_team="data-platform"
    )
    make_finding(
        session, native_id="x#3", severity=Severity.critical, owner_team="io-data-eng"
    )
    session.commit()

    scoped = client.get("/metrics/summary?executive_pillar=product", headers=EXEC).json()
    assert scoped["open_criticals"] == 2

    aliased = client.get("/metrics/summary?pillar=product", headers=EXEC).json()
    assert aliased["open_criticals"] == 2


def test_security_posture_application_and_service_filters(session, client) -> None:
    make_finding(
        session,
        native_id="ExampleOrg/example-service#1",
        severity=Severity.critical,
        owner_team="pricing-platform",
    )
    make_finding(
        session,
        native_id="ExampleOrg/another-service#1",
        severity=Severity.critical,
        owner_team="data-platform",
    )
    session.commit()

    by_app = client.get("/metrics/security-posture?application=pricing-app", headers=EXEC)
    assert by_app.status_code == 200
    assert by_app.json()["open_criticals"] == 1

    by_service = client.get(
        "/metrics/security-posture?service=pricing-service", headers=EXEC
    )
    assert by_service.status_code == 200
    assert by_service.json()["open_criticals"] == 1


def test_metrics_repo_filter_accepts_bare_repo(session, client) -> None:
    make_finding(
        session,
        native_id="ExampleOrg/example-service#1",
        severity=Severity.critical,
        owner_team="pricing-platform",
    )
    make_finding(
        session,
        native_id="ExampleOrg/another-service#1",
        severity=Severity.critical,
        owner_team="data-platform",
    )
    session.commit()

    body = client.get("/metrics/summary?repo=example-service", headers=EXEC).json()
    assert body["open_criticals"] == 1


def test_summary_wow_delta_null_when_observation_window_under_7d(session, client) -> None:
    """A freshly-seeded DB (every finding first_seen < 7d ago) must surface
    `open_criticals_wow_delta = null`, not 0. `_open_critical_count_at` uses
    the SLA anchor (`upstream_created_at`) to decide which findings "existed
    7d ago", which for Sonar (upstream timestamps going back years) gives a
    confidently-wrong +0 WoW on day 1 of observation. The frontend renders
    `history < 7d` from the null instead. Reported 2026-05-18 on /executive.
    """
    make_finding(
        session,
        native_id="fresh#1",
        severity=Severity.critical,
        age_days=2,            # ingested 2 days ago
        upstream_age_days=400, # upstream says it's been around forever
    )
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["open_criticals"] == 1
    assert body["open_criticals_wow_delta"] is None
    assert body["observed_since"] is not None


def test_summary_wow_delta_computed_when_observation_window_over_7d(session, client) -> None:
    """Once we have >=7d of observation history, the WoW delta is meaningful
    again. With one critical first_seen 10d ago and no closures, the count
    matches both now and 7d ago, so delta == 0 — but that 0 is *actual*
    week-over-week stability, not a "no history" artifact."""
    make_finding(
        session,
        native_id="aged#1",
        severity=Severity.critical,
        age_days=10,
        upstream_age_days=400,
    )
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["open_criticals"] == 1
    assert body["open_criticals_wow_delta"] == 0  # honest 0, not null


def test_summary_observed_since_null_when_scope_empty(session, client) -> None:
    """Empty in-scope set -> `observed_since` is null (and WoW is null too).
    The frontend renders the WoW card as "—" without a misleading delta."""
    body = client.get("/metrics/summary?team=nonexistent-team", headers=EXEC).json()
    assert body["open_criticals"] == 0
    assert body["open_criticals_wow_delta"] is None
    assert body["observed_since"] is None


def test_summary_observed_since_narrows_with_team_filter(session, client) -> None:
    """`observed_since` is computed AFTER the `?team=` filter — a pillar with
    only freshly-seen findings gets a null WoW even if the org has older data
    elsewhere. This pins the "the Product pillar specifically only has 3d of
    history" behaviour reported on /executive 2026-05-18."""
    make_finding(
        session,
        native_id="old-team#1",
        severity=Severity.critical,
        age_days=30,
        owner_team="legacy-translator",
    )
    make_finding(
        session,
        native_id="new-team#1",
        severity=Severity.critical,
        age_days=2,
        owner_team="order",
    )
    session.commit()

    # Org-wide view sees the 30d-old finding -> WoW is computed.
    org = client.get("/metrics/summary", headers=EXEC).json()
    assert org["open_criticals_wow_delta"] is not None

    # Product scope only sees the 2d-old `order` finding -> WoW nulled.
    scoped = client.get("/metrics/summary?team=order", headers=EXEC).json()
    assert scoped["open_criticals"] == 1
    assert scoped["open_criticals_wow_delta"] is None


def test_summary_sla_compliance(session, client) -> None:
    # critical SLA = 7d; medium SLA = 90d
    make_finding(session, native_id="x#1", severity=Severity.critical, age_days=10)  # breached
    make_finding(session, native_id="x#2", severity=Severity.critical, age_days=2)  # ok
    make_finding(session, native_id="x#3", severity=Severity.medium, age_days=10)  # ok (90d)
    session.commit()

    r = client.get("/metrics/summary", headers=EXEC)
    body = r.json()
    # 1 of 3 breached -> 66.7% compliance
    assert body["sla_compliance_pct"] == pytest.approx(66.7, abs=0.5)


def test_top_teams_excludes_unowned(session, client) -> None:
    """Exec leaderboard is team-attributable; unowned isn't a team. Pinned by
    the routes_metrics docstring + this test. Unowned remains in /summary
    totals (the headline number) and on /admin (the triage queue)."""
    for i in range(5):
        make_finding(
            session,
            native_id=f"unowned#{i}",
            severity=Severity.critical,
            owner_team="unowned",
        )
    make_finding(
        session, native_id="real#1", severity=Severity.critical, owner_team="legacy-translator"
    )
    session.commit()

    rows = client.get("/metrics/top-teams", headers=EXEC).json()
    teams_returned = [r["team"] for r in rows]
    assert "unowned" not in teams_returned
    assert "legacy-translator" in teams_returned


def test_sla_breaches_excludes_unowned(session, client) -> None:
    """Exec breach list excludes unowned for the same reason as top-teams —
    breach attribution is the point of the leaderboard, and 'unowned' isn't
    an attribution. Unowned breaches are visible on /admin."""
    make_finding(
        session, native_id="ub#1", severity=Severity.critical,
        owner_team="unowned", age_days=30,
    )
    make_finding(
        session, native_id="rb#1", severity=Severity.critical,
        owner_team="legacy-translator", age_days=30,
    )
    session.commit()

    rows = client.get("/metrics/sla-breaches", headers=EXEC).json()
    teams_returned = [r["owner_team"] for r in rows]
    assert "unowned" not in teams_returned
    assert "legacy-translator" in teams_returned


def test_top_teams_only_critical_and_high(session, client) -> None:
    for i in range(3):
        make_finding(
            session,
            native_id=f"ExampleOrg/example-service#{i}",
            owner_team="pricing-platform",
            severity=Severity.critical,
        )
    for i in range(2):
        make_finding(
            session,
            native_id=f"ExampleOrg/another-service#{i}",
            owner_team="data-platform",
            severity=Severity.high,
        )
    make_finding(
        session,
        native_id="ExampleOrg/example-service#9",
        owner_team="pricing-platform",
        severity=Severity.low,  # excluded
    )
    session.commit()

    r = client.get("/metrics/top-teams", headers=EXEC)
    body = r.json()
    assert body[0] == {
        "team": "pricing-platform",
        "open_criticals": 3,
        "open_highs": 0,
        "open_count": 3,
    }
    assert body[1] == {
        "team": "data-platform",
        "open_criticals": 0,
        "open_highs": 2,
        "open_count": 2,
    }


def test_sla_breaches_lists_oldest(session, client) -> None:
    make_finding(session, native_id="a#1", severity=Severity.critical, age_days=20)  # breached
    make_finding(session, native_id="a#2", severity=Severity.critical, age_days=15)  # breached
    make_finding(session, native_id="a#3", severity=Severity.critical, age_days=2)  # not
    session.commit()

    r = client.get("/metrics/sla-breaches", headers=EXEC)
    body = r.json()
    assert len(body) == 2
    assert body[0]["age_days"] > body[1]["age_days"]


def test_trend_returns_open_count_per_day(session, client) -> None:
    make_finding(session, native_id="t#1", severity=Severity.high, age_days=5)
    make_finding(session, native_id="t#2", severity=Severity.high, age_days=2)
    session.commit()
    _seed_daily_metrics_for_trend(session)

    r = client.get("/metrics/trend?days=7", headers=EXEC)
    body = r.json()
    assert body["window_days"] == 7
    # Earliest day in window has 0 findings (both seen later); latest has 2
    by_date = {(p["date"], p["severity"]): p["open_count"] for p in body["points"]}
    assert max(by_date.values()) == 2


def test_sla_compliance_uses_upstream_created_at_not_ingest(session, client) -> None:
    """A 30-day-old GitHub alert ingested today must breach the 7d critical SLA —
    even though our `first_seen_at` is essentially `now`."""
    make_finding(
        session,
        native_id="recent-ingest#1",
        severity=Severity.critical,
        age_days=0.01,           # just ingested
        upstream_age_days=30,    # but GitHub created it 30 days ago
    )
    session.commit()

    r = client.get("/metrics/summary", headers=EXEC)
    body = r.json()
    assert body["sla_compliance_pct"] == 0.0  # the only finding is breached


def test_reopen_does_not_reset_sla_clock(session, client) -> None:
    """A reopened critical alert with a 400-day-old upstream `creationDate`
    must still be SLA-breached after reopen — the anchor stays at the
    upstream creation timestamp.

    The original spec restarted the SLA window on reopen, on the rationale
    that "a re-introduced vulnerability deserves a fresh look". The cloud
    rollout exposed why that's wrong: the SonarCloud multi-org cross-
    contamination (commit 8d11948) bulk-auto-closed and then bulk-reopened
    1k+ valid findings within minutes of each other, which under the old
    anchor reset every Sonar finding's age to "3 hours" and inflated SLA
    compliance overnight. Sonar's own `creationDate` is the canonical
    "when did this vulnerability first appear?" record; real
    re-introductions surface as new issue keys (and thus new
    `upstream_created_at` values) anyway. Anchor on that, not on our
    dashboard-internal reopen lifecycle. See `app/api/sla.py`.
    """
    make_finding(
        session,
        native_id="reopened#1",
        severity=Severity.critical,
        age_days=400,
        upstream_age_days=400,
        reopened_days_ago=1,
    )
    session.commit()

    r = client.get("/metrics/summary", headers=EXEC)
    body = r.json()
    # Critical SLA window is 7 days; anchor is 400d ago → breached.
    assert body["sla_compliance_pct"] == 0.0


def test_security_posture_team_filter_narrows_results(session, client) -> None:
    """`?team=` further narrows AFTER RBAC scoping. Used by the Platform
    view to focus the chart surface on `io-platform-eng` regardless of who's
    looking (admin or platform-team member)."""
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    make_finding(
        session, native_id="plat#2", severity=Severity.high, owner_team="io-platform-eng"
    )
    make_finding(
        session, native_id="other#1", severity=Severity.critical, owner_team="legacy-translator"
    )
    session.commit()

    # Without filter: executive sees everything (2 crit + 1 high).
    r = client.get("/metrics/security-posture", headers=EXEC)
    assert r.json()["open_criticals"] == 2

    # With filter: scoped to io-platform-eng only (1 crit + 1 high).
    r = client.get("/metrics/security-posture?team=io-platform-eng", headers=EXEC)
    body = r.json()
    assert body["open_criticals"] == 1
    assert body["open_highs"] == 1


def test_security_posture_team_filter_returns_empty_when_no_match(session, client) -> None:
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    session.commit()

    r = client.get("/metrics/security-posture?team=nonexistent-team", headers=EXEC)
    body = r.json()
    assert body["open_criticals"] == 0
    assert body["open_highs"] == 0
    assert body["sonarcloud"] == {"criticals": 0, "highs": 0}
    assert body["dependabot"] == {"criticals": 0, "highs": 0}


def test_trend_team_filter_narrows_results(session, client) -> None:
    make_finding(
        session, native_id="t-plat#1", severity=Severity.high, age_days=2, owner_team="io-platform-eng"
    )
    make_finding(
        session, native_id="t-other#1", severity=Severity.high, age_days=2, owner_team="legacy-translator"
    )
    session.commit()
    _seed_daily_metrics_for_trend(session)

    r_all = client.get("/metrics/trend?days=7", headers=EXEC)
    r_plat = client.get("/metrics/trend?days=7&team=io-platform-eng", headers=EXEC)

    # Sum the open_count across all points; the team-scoped sum is half.
    sum_all = sum(p["open_count"] for p in r_all.json()["points"])
    sum_plat = sum(p["open_count"] for p in r_plat.json()["points"])
    assert sum_all == 2 * sum_plat


def test_security_posture_multi_team_filter_unions_results(session, client) -> None:
    """repeating `?team=` unions across teams.
    Used by /platform pillar tabs (io-platform-eng / product-platform / retail) — the
    page name 'Platform' covers both subteams, so the filter has to span both."""
    make_finding(
        session, native_id="ipe#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    make_finding(
        session, native_id="cops#1", severity=Severity.critical, owner_team="product-platform"
    )
    make_finding(
        session, native_id="other#1", severity=Severity.critical, owner_team="legacy-translator"
    )
    session.commit()

    # Single-team (legacy semantics, must still work) — 1 crit each.
    assert client.get("/metrics/security-posture?team=io-platform-eng", headers=EXEC).json()["open_criticals"] == 1
    assert client.get("/metrics/security-posture?team=product-platform", headers=EXEC).json()["open_criticals"] == 1

    # Multi-team union — 2 crits (both platform teams), excluding legacy-translator.
    body = client.get(
        "/metrics/security-posture?team=io-platform-eng&team=product-platform",
        headers=EXEC,
    ).json()
    assert body["open_criticals"] == 2


def test_findings_multi_team_filter_unions_results(session, client) -> None:
    """Same union semantics on /findings — the FindingsTable on /platform sends
    the same multi-team query, otherwise the disclosure-expanded table would
    only show one subteam's rows."""
    make_finding(session, native_id="ipe#x", owner_team="io-platform-eng")
    make_finding(session, native_id="cops#x", owner_team="product-platform")
    make_finding(session, native_id="other#x", owner_team="legacy-translator")
    session.commit()

    body = client.get(
        "/findings?team=io-platform-eng&team=product-platform", headers=EXEC
    ).json()
    teams = {f["owner_team"] for f in body["items"]}
    assert teams == {"io-platform-eng", "product-platform"}


def test_security_posture_asset_filter_narrows_by_substring(session, client) -> None:
    """2026-05-18 dev-view rework: clicking a *service* row sends `?asset=<repo>`
    (or `?asset=<sonar-project-key>` for the Retail monorepo case). The filter
    is a case-insensitive substring on `asset_display`, mirroring /findings.
    Without this, selecting a service couldn't narrow the page-top KPI cards.

    The factory derives asset_display from native_id's pre-`#` segment, so we
    use raw Sonar project keys / repo paths as the native_id prefix here."""
    make_finding(
        session,
        native_id="ExampleOrg.Commerce.Orders.API#1",
        severity=Severity.critical,
        owner_team="retail-order",
    )
    make_finding(
        session,
        native_id="ExampleOrg.Commerce.Offers.API#1",
        severity=Severity.critical,
        owner_team="retail-offer",
    )
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#1",
        severity=Severity.critical,
        owner_team="order",
    )
    session.commit()

    # No filter -> all three criticals.
    assert client.get("/metrics/security-posture", headers=EXEC).json()["open_criticals"] == 3
    # Substring match on a Sonar project key -> just that one.
    body = client.get(
        "/metrics/security-posture?asset=ExampleOrg.Commerce.Orders.API", headers=EXEC
    ).json()
    assert body["open_criticals"] == 1
    # Substring partial -> only the convention-path asset.
    body = client.get(
        "/metrics/security-posture?asset=orders-api", headers=EXEC
    ).json()
    assert body["open_criticals"] == 1


def test_security_posture_asset_filter_composes_with_team(session, client) -> None:
    """The selection params compose with AND so application-level selection
    (team union) + a service refinement (asset) still narrows further. We pin
    this so a future refactor that special-cases asset-XOR-team breaks here."""
    make_finding(
        session,
        native_id="ExampleOrg.Commerce.Orders.API#1",
        severity=Severity.critical,
        owner_team="retail-order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/retail-api#1",  # same team, different asset
        severity=Severity.critical,
        owner_team="retail-order",
    )
    make_finding(
        session,
        native_id="ExampleOrg.Commerce.Cart.API#1",
        severity=Severity.critical,
        owner_team="retail-cart",
    )
    session.commit()

    # Team alone: 2 retail-order findings.
    assert client.get(
        "/metrics/security-posture?team=retail-order", headers=EXEC
    ).json()["open_criticals"] == 2
    # Asset alone: only ExampleOrg.Commerce.Orders.API -> 1 finding.
    assert client.get(
        "/metrics/security-posture?asset=ExampleOrg.Commerce.Orders.API", headers=EXEC
    ).json()["open_criticals"] == 1
    # Both -> AND -> still 1 (intersection of {retail-order} and {Order.API}).
    assert client.get(
        "/metrics/security-posture?team=retail-order&asset=ExampleOrg.Commerce.Orders.API",
        headers=EXEC,
    ).json()["open_criticals"] == 1


def test_trend_asset_filter_narrows_results(session, client) -> None:
    """`?asset=` is wired through /metrics/trend too, so the trend chart on the
    Developer view narrows in lockstep with the rating cards when a service
    row is selected."""
    make_finding(
        session,
        native_id="ExampleOrg.Commerce.Orders.API#1",
        severity=Severity.high,
        age_days=2,
    )
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#1",
        severity=Severity.high,
        age_days=2,
    )
    session.commit()
    _seed_daily_metrics_for_trend(session)

    r_all = client.get("/metrics/trend?days=7", headers=EXEC)
    r_filtered = client.get(
        "/metrics/trend?days=7&asset=ExampleOrg.Commerce.Orders.API", headers=EXEC
    )

    def _sum_latest_day(resp) -> int:
        points = resp.json()["points"]
        if not points:
            return 0
        latest = max(p["date"] for p in points)
        return sum(p["open_count"] for p in points if p["date"] == latest)

    # Compare the most recent rollup day — summing the whole window double-counts
    # open snapshots across days (daily_metrics path) vs replay (asset path).
    assert _sum_latest_day(r_all) == 2 * _sum_latest_day(r_filtered)


def test_team_filter_does_not_bypass_rbac(session, client) -> None:
    """`?team=` is a pure query narrowing — any authenticated caller can ask
    for any team and the backend returns that team's findings. There is no
    per-user team-scoping gate any more (collapse); the LB-level
    IAP allowlist is the only access control. Pinning that the filter still
    narrows correctly to the requested team."""
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    session.commit()

    alice = {
        "X-Dev-Identity": json.dumps(
            {"email": "alice@example.com", "google.groups": ["engineering@example.com"]}
        ),
    }
    r = client.get("/metrics/security-posture?team=io-platform-eng", headers=alice)
    assert r.status_code == 200
    assert r.json()["open_criticals"] == 1


# ---------------------------------------------------------------------------
# Executive view per-pillar scoping
#
# `/metrics/summary` and `/metrics/top-teams` learned `?team=` (multi, union)
# so the executive view can scope its KPI strip and offender list to one
# pillar's team set at a time. `/metrics/top-services` is a new sister to
# /top-teams for the By Service mode of the offender list.
# ---------------------------------------------------------------------------


def test_summary_team_filter_narrows_results(session, client) -> None:
    """`/metrics/summary?team=foo` scopes the KPI counts (open criticals + SLA
    compliance) to that team only. Powers the executive view's per-pillar KPI
    strip — the same headline numbers, but bounded to the selected pillar."""
    make_finding(
        session, native_id="ord#1", severity=Severity.critical, owner_team="order"
    )
    make_finding(
        session, native_id="ord#2", severity=Severity.critical, owner_team="order"
    )
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    session.commit()

    # No filter -> exec sees everything (3 criticals).
    assert client.get("/metrics/summary", headers=EXEC).json()["open_criticals"] == 3
    # Scoped to `order` -> just the two ord#* criticals.
    body = client.get("/metrics/summary?team=order", headers=EXEC).json()
    assert body["open_criticals"] == 2


def test_summary_multi_team_filter_unions_results(session, client) -> None:
    """Pillar scoping is union-semantics across the pillar's team set."""
    make_finding(session, native_id="ord#1", severity=Severity.critical, owner_team="order")
    make_finding(session, native_id="ofr#1", severity=Severity.critical, owner_team="offer")
    make_finding(session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng")
    session.commit()

    # Two-team union (a stand-in for "this pillar"): 2 of the 3 criticals.
    body = client.get(
        "/metrics/summary?team=order&team=offer", headers=EXEC
    ).json()
    assert body["open_criticals"] == 2


def test_summary_team_filter_returns_requested_team(session, client) -> None:
    """`?team=` on /metrics/summary is a pure query narrowing — same as on
    /security-posture. The pre-collapse RBAC gate that used to enforce
    "developer not on this team -> zero" no longer exists; the LB is the
    only gate."""
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    session.commit()

    alice = {
        "X-Dev-Identity": json.dumps(
            {"email": "alice@example.com", "google.groups": ["engineering@example.com"]}
        ),
    }
    body = client.get(
        "/metrics/summary?team=io-platform-eng", headers=alice
    ).json()
    assert body["open_criticals"] == 1


def test_top_teams_team_filter_narrows_to_pillar(session, client) -> None:
    """`/metrics/top-teams?team=...` (multi) scopes the leaderboard to the
    requested pillar's team set. The ranking is still global-within-scope
    (most → least open crit+high), and `unowned` is still excluded."""
    make_finding(session, native_id="ord#1", severity=Severity.critical, owner_team="order")
    make_finding(session, native_id="ord#2", severity=Severity.high, owner_team="order")
    make_finding(session, native_id="ofr#1", severity=Severity.critical, owner_team="offer")
    # Out-of-pillar team — must not appear in the result even if it has more findings.
    make_finding(session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng")
    make_finding(session, native_id="plat#2", severity=Severity.critical, owner_team="io-platform-eng")
    make_finding(session, native_id="plat#3", severity=Severity.high, owner_team="io-platform-eng")
    session.commit()

    body = client.get(
        "/metrics/top-teams?team=order&team=offer", headers=EXEC
    ).json()
    teams_returned = {r["team"] for r in body}
    assert teams_returned == {"order", "offer"}
    # Order has 2, offer has 1 — most-offending first.
    assert body[0] == {
        "team": "order",
        "open_criticals": 1,
        "open_highs": 1,
        "open_count": 2,
    }
    assert body[1] == {
        "team": "offer",
        "open_criticals": 1,
        "open_highs": 0,
        "open_count": 1,
    }


def test_top_teams_team_filter_returns_requested_team(session, client) -> None:
    """`?team=` on /metrics/top-teams is a pure query narrowing for any
    authenticated caller. The pre-collapse RBAC gate is gone."""
    make_finding(
        session, native_id="plat#1", severity=Severity.critical, owner_team="io-platform-eng"
    )
    session.commit()

    alice = {
        "X-Dev-Identity": json.dumps(
            {"email": "alice@example.com", "google.groups": ["engineering@example.com"]}
        ),
    }
    body = client.get(
        "/metrics/top-teams?team=io-platform-eng", headers=alice
    ).json()
    assert len(body) == 1
    assert body[0]["team"] == "io-platform-eng"
    assert body[0]["open_criticals"] == 1


def test_top_services_groups_by_asset(session, client) -> None:
    """`/metrics/top-services` aggregates by (asset_display, owner_team) and
    ranks by open crit+high. Same `unowned` exclusion as /top-teams; same
    crit+high severity filter."""
    # Two findings on one asset for `order`.
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#1",
        severity=Severity.critical,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#2",
        severity=Severity.high,
        owner_team="order",
    )
    # One finding on a different asset for the same team.
    make_finding(
        session,
        native_id="ExampleOrg/orders-history#1",
        severity=Severity.critical,
        owner_team="order",
    )
    # Unowned must be excluded.
    make_finding(
        session,
        native_id="ExampleOrg/orphan#1",
        severity=Severity.critical,
        owner_team="unowned",
    )
    # Medium severity must be excluded (crit+high only).
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#3",
        severity=Severity.medium,
        owner_team="order",
    )
    session.commit()

    body = client.get("/metrics/top-services", headers=EXEC).json()
    asset_to_count = {r["asset_display"]: r["open_count"] for r in body}
    assert "ExampleOrg/orphan" not in asset_to_count
    assert asset_to_count["ExampleOrg/orders-api"] == 2  # 1 crit + 1 high
    assert asset_to_count["ExampleOrg/orders-history"] == 1
    # And the per-severity split lines up — the offender list needs it to map
    # critical-vs-high counts per repo on row expand.
    orderengine = next(
        r for r in body if r["asset_display"] == "ExampleOrg/orders-api"
    )
    assert orderengine["open_criticals"] == 1
    assert orderengine["open_highs"] == 1
    # Most-offending first.
    assert body[0]["asset_display"] == "ExampleOrg/orders-api"


def test_top_teams_splits_open_count_by_severity(session, client) -> None:
    """The exec offender list renders "5 critical · 12 high" per team, so the
    endpoint must return the per-severity split (`open_criticals` /
    `open_highs`), not just the conflated `open_count`. Two teams with
    identical totals but different mixes must look different on the page.
    """
    # Team A: 2 critical, 1 high  -> total 3
    make_finding(session, native_id="a#1", severity=Severity.critical, owner_team="order")
    make_finding(session, native_id="a#2", severity=Severity.critical, owner_team="order")
    make_finding(session, native_id="a#3", severity=Severity.high, owner_team="order")
    # Team B: 0 critical, 3 high  -> total 3 (same as A)
    make_finding(session, native_id="b#1", severity=Severity.high, owner_team="offer")
    make_finding(session, native_id="b#2", severity=Severity.high, owner_team="offer")
    make_finding(session, native_id="b#3", severity=Severity.high, owner_team="offer")
    session.commit()

    body = client.get("/metrics/top-teams", headers=EXEC).json()
    by_team = {row["team"]: row for row in body}
    assert by_team["order"]["open_criticals"] == 2
    assert by_team["order"]["open_highs"] == 1
    assert by_team["order"]["open_count"] == 3
    assert by_team["offer"]["open_criticals"] == 0
    assert by_team["offer"]["open_highs"] == 3
    assert by_team["offer"]["open_count"] == 3


def test_top_services_splits_open_count_by_severity(session, client) -> None:
    """Same per-severity split on the `By service` endpoint — the offender
    list expands a team row into its services and the per-service breakdown
    must be mapped to the repo without a second `/findings` query."""
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#c1",
        severity=Severity.critical,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#h1",
        severity=Severity.high,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#h2",
        severity=Severity.high,
        owner_team="order",
    )
    session.commit()

    body = client.get("/metrics/top-services", headers=EXEC).json()
    row = next(r for r in body if r["asset_display"] == "ExampleOrg/orders-api")
    assert row["open_criticals"] == 1
    assert row["open_highs"] == 2
    assert row["open_count"] == 3


def test_platform_wiz_issues_only_scopes_platform_teams(session, client) -> None:
    """Exec detail offender list counts Wiz Issues only for platform teams."""
    from app.core.models import Finding

    make_finding(
        session,
        native_id="wiz:cpe-issue",
        source="wiz",
        severity=Severity.critical,
        owner_team="product-platform",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:cpe-issue").one().wiz_category = "issue"
    make_finding(
        session,
        native_id="wiz:cpe-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="product-platform",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:cpe-cfg").one().wiz_category = "cloud_config"
    make_finding(
        session,
        native_id="wiz:order-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:order-cfg").one().wiz_category = "cloud_config"
    session.commit()

    qs = "team=product-platform&team=order"
    unscoped = {
        r["team"]: r
        for r in client.get(f"/metrics/top-teams?{qs}", headers=EXEC).json()
    }
    assert unscoped["product-platform"]["open_criticals"] == 2
    assert unscoped["order"]["open_criticals"] == 1

    scoped = {
        r["team"]: r
        for r in client.get(
            f"/metrics/top-teams?{qs}&platform_wiz_issues_only=true",
            headers=EXEC,
        ).json()
    }
    assert scoped["product-platform"]["open_criticals"] == 1
    assert scoped["order"]["open_criticals"] == 1

    make_finding(
        session,
        native_id="wiz:cpe-high-cfg",
        source="wiz",
        severity=Severity.high,
        owner_team="product-platform",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:cpe-high-cfg").one().wiz_category = (
        "cloud_config"
    )
    session.commit()

    posture_unscoped = client.get(
        f"/metrics/security-posture?{qs}",
        headers=EXEC,
    ).json()
    assert posture_unscoped["open_criticals"] == 3
    assert posture_unscoped["open_highs"] == 1

    posture_scoped = client.get(
        f"/metrics/security-posture?{qs}&platform_wiz_issues_only=true",
        headers=EXEC,
    ).json()
    assert posture_scoped["open_criticals"] == 2
    assert posture_scoped["open_highs"] == 0

    summary_unscoped = client.get(
        f"/metrics/summary?{qs}",
        headers=EXEC,
    ).json()
    buckets_unscoped = summary_unscoped["age_buckets_open_crit_high"]
    assert sum(buckets_unscoped.values()) == 4

    summary_scoped = client.get(
        f"/metrics/summary?{qs}&platform_wiz_issues_only=true",
        headers=EXEC,
    ).json()
    buckets_scoped = summary_scoped["age_buckets_open_crit_high"]
    assert sum(buckets_scoped.values()) == 2
    assert summary_scoped["open_criticals"] == 2

    trend_scoped = client.get(
        f"/metrics/trend?days=7&{qs}&platform_wiz_issues_only=true",
        headers=EXEC,
    ).json()
    latest = {}
    for point in trend_scoped["points"]:
        latest[point["severity"]] = point["open_count"]
    assert latest.get("critical") == 2
    assert latest.get("high", 0) == 0


def test_platform_overview_wiz_rating_issues_only(session, client) -> None:
    """Overview Wiz card on /platform counts Issues only; other categories stay on /platform/wiz."""
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz:product-issue",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:product-issue").one().wiz_category = "issue"
    make_finding(
        session,
        native_id="wiz:product-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:product-cfg").one().wiz_category = "cloud_config"
    make_finding(
        session,
        native_id="wiz:product-vuln",
        source="wiz",
        severity=Severity.high,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:product-vuln").one().wiz_category = "vulnerability"
    session.commit()

    qs = "platform_pillar=product&team=product-platform&team=order"
    ratings = {
        x["source"]: x
        for x in client.get(
            f"/metrics/security-posture?{qs}&platform_wiz_issues_only=true",
            headers=EXEC,
        ).json()["source_ratings"]
    }
    assert ratings["wiz"]["open_criticals"] == 1
    assert ratings["wiz"]["open_highs"] == 0

    unscoped = {
        x["source"]: x
        for x in client.get(f"/metrics/security-posture?{qs}", headers=EXEC).json()[
            "source_ratings"
        ]
    }
    assert unscoped["wiz"]["open_criticals"] == 2
    assert unscoped["wiz"]["open_highs"] == 1

    wiz_tab = client.get(
        f"/findings/wiz-by-category?{qs}",
        headers=EXEC,
    ).json()
    assert wiz_tab["total"] == 3


def test_platform_overview_trend_matches_posture_with_wiz_issues_only(
    session, client
) -> None:
    """Overview trend chart must use the same issues-only Wiz scope as the KPI boxes."""
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz:trend-issue",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:trend-issue").one().wiz_category = "issue"
    make_finding(
        session,
        native_id="wiz:trend-cfg",
        source="wiz",
        severity=Severity.critical,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:trend-cfg").one().wiz_category = "cloud_config"
    make_finding(
        session,
        native_id="wiz:trend-vuln",
        source="wiz",
        severity=Severity.high,
        owner_team="order",
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:trend-vuln").one().wiz_category = "vulnerability"
    session.commit()

    qs = "platform_pillar=product&team=product-platform&team=order"
    issues_qs = f"{qs}&platform_wiz_issues_only=true"
    posture = client.get(
        f"/metrics/security-posture?{issues_qs}",
        headers=EXEC,
    ).json()
    trend = client.get(
        f"/metrics/trend?days=30&{issues_qs}",
        headers=EXEC,
    ).json()
    today = date.today().isoformat()
    by_sev = {
        p["severity"]: p["open_count"]
        for p in trend["points"]
        if p["date"] == today
    }
    assert by_sev.get("critical", 0) == posture["open_criticals"]
    assert by_sev.get("high", 0) == posture["open_highs"]
    assert posture["open_criticals"] == 1
    assert posture["open_highs"] == 0

    unscoped_trend = client.get(
        f"/metrics/trend?days=30&{qs}",
        headers=EXEC,
    ).json()
    unscoped_by_sev = {
        p["severity"]: p["open_count"]
        for p in unscoped_trend["points"]
        if p["date"] == today
    }
    assert unscoped_by_sev.get("critical", 0) > posture["open_criticals"]
    assert unscoped_by_sev.get("high", 0) > posture["open_highs"]


def test_platform_pillar_issues_only_keeps_non_wiz_in_headline_totals(
    session, client
) -> None:
    """Headline open counts must not drop Sonar/Dependabot when Wiz is issues-only."""
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="dep:retail-high",
        source="dependabot",
        severity=Severity.high,
        owner_team="platform-retail",
    )
    make_finding(
        session,
        native_id="son:io-crit",
        source="sonarcloud",
        severity=Severity.critical,
        owner_team="io-platform-eng",
    )
    make_finding(
        session,
        native_id="wiz:retail-cfg",
        source="wiz",
        severity=Severity.high,
        owner_team="platform-retail",
        tags=["platform_pillar:retail"],
    )
    session.flush()
    session.query(Finding).filter_by(native_id="wiz:retail-cfg").one().wiz_category = (
        "cloud_config"
    )
    session.commit()

    retail_qs = "platform_pillar=retail&team=platform-retail&platform_wiz_issues_only=true"
    retail = client.get(f"/metrics/security-posture?{retail_qs}", headers=EXEC).json()
    assert retail["open_highs"] == 1
    retail_ratings = {r["source"]: r for r in retail["source_ratings"]}
    assert retail_ratings["dependabot"]["open_highs"] == 1
    assert retail_ratings["wiz"]["open_highs"] == 0

    io_qs = "platform_pillar=io&team=io-platform-eng&platform_wiz_issues_only=true"
    io = client.get(f"/metrics/security-posture?{io_qs}", headers=EXEC).json()
    assert io["open_criticals"] == 1
    io_ratings = {r["source"]: r for r in io["source_ratings"]}
    assert io_ratings["sonarcloud"]["open_criticals"] == 1
    assert io["open_criticals"] == io_ratings["sonarcloud"]["open_criticals"]


def test_top_services_team_filter_unions_results(session, client) -> None:
    """Same multi-team union semantics as /top-teams — used by the executive
    view's `By service` mode to rank service-level offenders within a pillar."""
    make_finding(
        session,
        native_id="ExampleOrg/orders-api#1",
        severity=Severity.critical,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="ExampleOrg/offers-api#1",
        severity=Severity.critical,
        owner_team="offer",
    )
    make_finding(
        session,
        native_id="ExampleOrg/platform#1",
        severity=Severity.critical,
        owner_team="io-platform-eng",
    )
    session.commit()

    body = client.get(
        "/metrics/top-services?team=order&team=offer", headers=EXEC
    ).json()
    owners = {r["owner_team"] for r in body}
    assert owners == {"order", "offer"}
    assert all(r["owner_team"] != "io-platform-eng" for r in body)


# ---------------------------------------------------------------------------
# Per-source rating ladders — first matching condition wins
# ---------------------------------------------------------------------------


def _ratings(client) -> dict[str, dict]:
    r = client.get("/metrics/security-posture", headers=EXEC)
    return {x["source"]: x for x in r.json()["source_ratings"]}


def _make_n(session, source: str, severity: Severity, n: int, prefix: str) -> None:
    for i in range(n):
        make_finding(session, native_id=f"{prefix}#{i}", source=source, severity=severity)


# --- Sonar ladder ----------------------------------------------------------


def test_sonar_rating_a_on_clean(session, client) -> None:
    assert _ratings(client)["sonarcloud"]["grade"] == "A"


def test_sonar_rating_b_band_top(session, client) -> None:
    """Boundary: 2 critical + 10 high == B."""
    _make_n(session, "sonarcloud", Severity.critical, 2, "sb-c")
    _make_n(session, "sonarcloud", Severity.high, 10, "sb-h")
    session.commit()
    assert _ratings(client)["sonarcloud"]["grade"] == "B"


def test_sonar_rating_c_band_bottom(session, client) -> None:
    """Boundary: 3 critical (or 11 high) trips C."""
    _make_n(session, "sonarcloud", Severity.critical, 3, "sc-c")
    session.commit()
    assert _ratings(client)["sonarcloud"]["grade"] == "C"


def test_sonar_rating_d_band(session, client) -> None:
    _make_n(session, "sonarcloud", Severity.critical, 11, "sd-c")
    session.commit()
    assert _ratings(client)["sonarcloud"]["grade"] == "D"


# --- Dependabot ladder (same shape as Sonar) -------------------------------


def test_dependabot_rating_a_on_clean(session, client) -> None:
    assert _ratings(client)["dependabot"]["grade"] == "A"


def test_dependabot_rating_b_band_top(session, client) -> None:
    _make_n(session, "dependabot", Severity.critical, 2, "db-c")
    _make_n(session, "dependabot", Severity.high, 10, "db-h")
    session.commit()
    assert _ratings(client)["dependabot"]["grade"] == "B"


def test_dependabot_rating_c_band(session, client) -> None:
    _make_n(session, "dependabot", Severity.high, 11, "dc-h")
    session.commit()
    assert _ratings(client)["dependabot"]["grade"] == "C"


def test_dependabot_rating_d_band(session, client) -> None:
    _make_n(session, "dependabot", Severity.high, 31, "dd-h")
    session.commit()
    assert _ratings(client)["dependabot"]["grade"] == "D"


# --- Pen.Test ladder (severity-weighted, intentionally stricter) -----------


def test_pentest_rating_a_on_clean_sheet(session, client) -> None:
    assert _ratings(client)["pentest"]["grade"] == "A"


def test_pentest_rating_b_low_impact_only(session, client) -> None:
    _make_n(session, "pentest", Severity.medium, 2, "pb-m")
    session.commit()
    assert _ratings(client)["pentest"]["grade"] == "B"


def test_pentest_rating_c_one_critical(session, client) -> None:
    """A single pentest critical = C (not D). User-locked: pentest is stricter
    than code scans because each pentest finding is a deliberate professional
    alarm, but a single one isn't yet emergency."""
    _make_n(session, "pentest", Severity.critical, 1, "pc-c")
    session.commit()
    assert _ratings(client)["pentest"]["grade"] == "C"


def test_pentest_rating_d_two_criticals(session, client) -> None:
    _make_n(session, "pentest", Severity.critical, 2, "pd-c")
    session.commit()
    assert _ratings(client)["pentest"]["grade"] == "D"


# --- Team scope + RBAC interaction --------


def test_wiz_rating_uses_high_volume_ladder(session, client) -> None:
    from sqlalchemy import update

    from app.core.models import Finding

    _make_n(session, "wiz", Severity.critical, 3, "wiz-c")
    session.execute(
        update(Finding).where(Finding.native_id.like("wiz-c%")).values(owner_team="order")
    )
    session.commit()
    ratings = {
        x["source"]: x["grade"]
        for x in client.get(
            "/metrics/security-posture?platform_pillar=product&team=product-platform",
            headers=EXEC,
        ).json()["source_ratings"]
    }
    assert ratings["wiz"] == "C"


def test_developer_posture_includes_wiz_rating(session, client) -> None:
    _make_n(session, "wiz", Severity.critical, 5, "wiz-only")
    session.commit()
    ratings = {
        x["source"]: x
        for x in client.get("/metrics/security-posture", headers=EXEC).json()["source_ratings"]
    }
    assert ratings["wiz"]["open_criticals"] == 5


def test_platform_pillar_scopes_unowned_wiz_by_subscription_tag(session, client) -> None:
    """Unowned Wiz appears only on the pillar tab matching platform_pillar:* tag."""
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz-unowned-product",
        source="wiz",
        owner_team="unowned",
        tags=["cloud_account:example-production-project", "platform_pillar:product"],
    )
    make_finding(
        session,
        native_id="wiz-unowned-product-cicd",
        source="wiz",
        owner_team="unowned",
        tags=["cloud_account:example-cicd-project", "platform_pillar:product"],
    )
    make_finding(
        session,
        native_id="wiz-unowned-io",
        source="wiz",
        owner_team="unowned",
        tags=["cloud_account:example-platform-project", "platform_pillar:io"],
    )
    make_finding(
        session,
        native_id="wiz-unowned-unmapped",
        source="wiz",
        owner_team="unowned",
        tags=["cloud_account:unknown-sub"],
    )
    session.commit()
    assert (
        client.get(
            "/findings?platform_pillar=product&team=product-platform&source=wiz",
            headers=EXEC,
        ).json()["total"]
        == 2
    )
    assert (
        client.get(
            "/findings?platform_pillar=io&team=io-platform-eng&source=wiz",
            headers=EXEC,
        ).json()["total"]
        == 1
    )
    assert (
        client.get(
            "/findings?platform_pillar=retail&team=platform-retail&source=wiz",
            headers=EXEC,
        ).json()["total"]
        == 0
    )


_PLATFORM_CODE_TEAM_BY_PILLAR = {
    "product": "product-platform",
    "retail": "platform-retail",
    "io": "io-platform-eng",
}


def _platform_pillar_scope_qs(client: TestClient, pillar: str) -> str:
    """Mirror `resolvePlatformScope` → repeated `team=` on /platform API calls."""
    indexes = client.get("/components", headers=EXEC).json()["indexes"]
    wiz_teams = indexes["wiz_teams_for_pillar"].get(pillar, [])
    code_team = _PLATFORM_CODE_TEAM_BY_PILLAR[pillar]
    teams = sorted({code_team, *wiz_teams})
    parts = [f"platform_pillar={pillar}"]
    for team in teams:
        parts.append(f"team={team}")
    return "&".join(parts)


def _wiz_overview_issue_counts(client: TestClient, scope_qs: str) -> tuple[int, int]:
    posture = client.get(
        f"/metrics/security-posture?{scope_qs}&platform_wiz_issues_only=true",
        headers=EXEC,
    ).json()
    wiz = next(r for r in posture["source_ratings"] if r["source"] == "wiz")
    return int(wiz["open_criticals"]), int(wiz["open_highs"])


def _wiz_findings_issue_counts(client: TestClient, scope_qs: str) -> tuple[int, int, int]:
    """Return (issue_category_count, criticals, highs) from `/findings/wiz-by-category`."""
    data = client.get(
        f"/findings/wiz-by-category?{scope_qs}",
        headers=EXEC,
    ).json()
    issue_group = next(
        (g for g in data["categories"] if g["wiz_category"] == "issue"),
        None,
    )
    if issue_group is None:
        return 0, 0, 0
    items = issue_group["items"]
    crit = sum(1 for item in items if item["severity"] == Severity.critical.value)
    high = sum(1 for item in items if item["severity"] == Severity.high.value)
    return int(issue_group["count"]), crit, high


def test_platform_overview_wiz_box_matches_wiz_findings_issues_all_pillars(
    session, client
) -> None:
    """Overview Wiz card (issues-only) must match Issues on /platform/wiz per pillar."""
    from app.core.models import Finding
    from tests._factory import make_finding

    seeds: list[tuple[str, str, Severity, str, list[str], str]] = [
        # pillar, wiz_category, severity, owner_team, tags, native_id
        (
            "product",
            "issue",
            Severity.critical,
            "product-platform",
            ["platform_pillar:product"],
            "align:product:pe-crit",
        ),
        (
            "product",
            "issue",
            Severity.high,
            "order",
            ["platform_pillar:product"],
            "align:product:order-high",
        ),
        (
            "product",
            "cloud_config",
            Severity.high,
            "product-platform",
            ["platform_pillar:product"],
            "align:product:cfg-noise",
        ),
        (
            "retail",
            "issue",
            Severity.high,
            "platform-retail",
            ["platform_pillar:retail"],
            "align:ra:issue",
        ),
        (
            "retail",
            "cloud_config",
            Severity.critical,
            "platform-retail",
            ["platform_pillar:retail"],
            "align:ra:cfg-noise",
        ),
        (
            "io",
            "issue",
            Severity.critical,
            "io-platform-eng",
            ["platform_pillar:io"],
            "align:io:issue",
        ),
        (
            "io",
            "vulnerability",
            Severity.high,
            "io-platform-eng",
            ["platform_pillar:io"],
            "align:io:vuln-noise",
        ),
    ]
    for _pillar, category, severity, owner, tags, native_id in seeds:
        make_finding(
            session,
            native_id=native_id,
            source="wiz",
            severity=severity,
            owner_team=owner,
            tags=tags,
        )
        session.flush()
        row = session.query(Finding).filter_by(native_id=native_id).one()
        row.wiz_category = category
    session.commit()

    for pillar in _PLATFORM_CODE_TEAM_BY_PILLAR:
        scope_qs = _platform_pillar_scope_qs(client, pillar)
        overview_crit, overview_high = _wiz_overview_issue_counts(client, scope_qs)
        issue_count, findings_crit, findings_high = _wiz_findings_issue_counts(
            client, scope_qs
        )

        assert overview_crit == findings_crit, pillar
        assert overview_high == findings_high, pillar
        assert overview_crit + overview_high == issue_count, pillar


def test_platform_pillar_includes_platform_code_owned_wiz(session, client) -> None:
    """cloudres Wiz owned by platform-retail from subscription pillar mapping."""
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz:retail-issue",
        source="wiz",
        owner_team="platform-retail",
        title="Service account with high privileges",
        tags=[
            "cloud_account:example-staging-project",
            "platform_pillar:retail",
        ],
    )
    session.flush()
    row = session.query(Finding).filter_by(native_id="wiz:retail-issue").one()
    row.wiz_category = "issue"
    session.commit()

    data = client.get(
        "/findings/wiz-by-category?platform_pillar=retail&team=platform-retail",
        headers=EXEC,
    ).json()
    assert data["total"] == 1
    assert data["categories"][0]["wiz_category"] == "issue"

    posture = client.get(
        "/metrics/security-posture?platform_pillar=retail&team=platform-retail"
        "&platform_wiz_issues_only=true",
        headers=EXEC,
    ).json()
    wiz_rating = next(r for r in posture["source_ratings"] if r["source"] == "wiz")
    assert wiz_rating["open_highs"] == 1
    assert posture["open_highs"] == 1

    assert (
        client.get(
            "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
            headers=EXEC,
        ).json()["total"]
        == 0
    )


def test_wiz_by_category_groups_and_links(session, client) -> None:
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz:aaa",
        source="wiz",
        owner_team="unowned",
        title="Issue finding",
        tags=["platform_pillar:product"],
    )
    session.flush()
    row = session.query(Finding).filter_by(native_id="wiz:aaa").one()
    row.wiz_category = "issue"
    make_finding(
        session,
        native_id="wiz:bbb",
        source="wiz",
        owner_team="unowned",
        title="CVE thing",
        tags=["platform_pillar:product"],
    )
    session.flush()
    row2 = session.query(Finding).filter_by(native_id="wiz:bbb").one()
    row2.wiz_category = "vulnerability"
    row2.upstream_url = (
        "https://app.wiz.io/explorer/vulnerability-findings"
        "#~(entity~(~'bbb*2cSECURITY_TOOL_FINDING))"
    )
    session.commit()

    data = client.get(
        "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
        headers=EXEC,
    ).json()
    assert data["total"] == 2
    by_cat = {g["wiz_category"]: g for g in data["categories"]}
    assert by_cat["issue"]["count"] == 1
    assert by_cat["vulnerability"]["count"] == 1
    assert (
        by_cat["issue"]["items"][0]["upstream_url"]
        == "https://app.wiz.io/issues#~(issue~'aaa)"
    )
    assert by_cat["vulnerability"]["items"][0]["upstream_url"].startswith(
        "https://app.wiz.io/explorer/"
    )


def test_wiz_by_category_groups_cloud_config_by_title(session, client) -> None:
    from app.core.models import Finding
    from tests._factory import make_finding

    titles = [
        "Ensure GKE cluster has private nodes enabled",
        "Ensure GKE cluster has private nodes enabled",
        "Ensure VPC flow logs are enabled",
    ]
    for idx, title in enumerate(titles):
        make_finding(
            session,
            native_id=f"wiz:cfg-{idx}",
            source="wiz",
            owner_team="product-platform",
            title=title,
            asset_id=f"cloudres:gcp/acct-{idx}/res-{idx}",
            tags=["platform_pillar:product"],
        )
        session.flush()
        row = session.query(Finding).filter_by(native_id=f"wiz:cfg-{idx}").one()
        row.wiz_category = "cloud_config"
    session.commit()

    data = client.get(
        "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
        headers=EXEC,
    ).json()
    cfg = next(g for g in data["categories"] if g["wiz_category"] == "cloud_config")
    assert cfg["count"] == 3
    assert len(cfg["title_groups"]) == 2
    by_title = {g["title"]: g for g in cfg["title_groups"]}
    assert by_title["Ensure GKE cluster has private nodes enabled"]["count"] == 2
    assert by_title["Ensure VPC flow logs are enabled"]["count"] == 1
    assert len(by_title["Ensure GKE cluster has private nodes enabled"]["items"]) == 2


def test_wiz_by_category_groups_vulnerability_by_cve(session, client) -> None:
    from app.core.models import Finding
    from tests._factory import make_finding

    specs = [
        ("CVE-2024-0001", "gke-node-a"),
        ("CVE-2024-0001", "gke-node-b"),
        ("CVE-2024-0002", "gke-node-c"),
    ]
    for idx, (cve, asset) in enumerate(specs):
        make_finding(
            session,
            native_id=f"wiz:vuln-{idx}",
            source="wiz",
            owner_team="product-platform",
            title=cve,
            asset_id=f"cloudres:gcp/acct-{idx}/{asset}",
            tags=["platform_pillar:product"],
        )
        session.flush()
        row = session.query(Finding).filter_by(native_id=f"wiz:vuln-{idx}").one()
        row.wiz_category = "vulnerability"
        row.cve_id = cve
        row.asset_display = asset
    session.commit()

    data = client.get(
        "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
        headers=EXEC,
    ).json()
    vuln = next(g for g in data["categories"] if g["wiz_category"] == "vulnerability")
    assert vuln["count"] == 3
    assert len(vuln["title_groups"]) == 2
    by_cve = {g["title"]: g for g in vuln["title_groups"]}
    assert by_cve["CVE-2024-0001"]["count"] == 2
    assert by_cve["CVE-2024-0002"]["count"] == 1
    assert by_cve["CVE-2024-0001"]["items"][0]["asset_display"] in {
        "gke-node-a",
        "gke-node-b",
    }


def test_wiz_by_category_groups_issues_by_title(session, client) -> None:
    from app.core.models import Finding
    from tests._factory import make_finding

    titles = [
        "Publicly exposed admin endpoint",
        "Publicly exposed admin endpoint",
        "Overly permissive IAM role",
    ]
    for idx, title in enumerate(titles):
        make_finding(
            session,
            native_id=f"wiz:issue-{idx}",
            source="wiz",
            owner_team="order",
            title=title,
            asset_id=f"wizservice:order-api-{idx}",
            tags=["platform_pillar:product"],
        )
        session.flush()
        row = session.query(Finding).filter_by(native_id=f"wiz:issue-{idx}").one()
        row.wiz_category = "issue"
    session.commit()

    data = client.get(
        "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
        headers=EXEC,
    ).json()
    issues = next(g for g in data["categories"] if g["wiz_category"] == "issue")
    assert issues["count"] == 3
    assert len(issues["title_groups"]) == 2
    by_title = {g["title"]: g for g in issues["title_groups"]}
    assert by_title["Publicly exposed admin endpoint"]["count"] == 2
    assert by_title["Overly permissive IAM role"]["count"] == 1


def test_threat_intel_pillar_scopes_threat_center_only(session, client) -> None:
    """Threat Center advisories live on the org-wide threat-intel tab, not product pillars."""
    from app.core.models import Finding
    from tests._factory import make_finding

    make_finding(
        session,
        native_id="wiz:threat:adv-1",
        source="wiz",
        owner_team="unowned",
        title="Starlette auth bypass",
        tags=["platform_pillar:threat-intel"],
    )
    session.flush()
    row = session.query(Finding).filter_by(native_id="wiz:threat:adv-1").one()
    row.wiz_category = "threat_center"
    make_finding(
        session,
        native_id="wiz:issue-product",
        source="wiz",
        owner_team="unowned",
        title="Misconfig in Product sub",
        tags=["platform_pillar:product"],
    )
    session.flush()
    row2 = session.query(Finding).filter_by(native_id="wiz:issue-product").one()
    row2.wiz_category = "issue"
    session.commit()

    product = client.get(
        "/findings/wiz-by-category?platform_pillar=product&team=product-platform",
        headers=EXEC,
    ).json()
    assert product["total"] == 1
    assert product["categories"][0]["wiz_category"] == "issue"

    intel = client.get(
        "/findings/wiz-by-category?platform_pillar=threat-intel",
        headers=EXEC,
    ).json()
    assert intel["total"] == 1
    assert intel["categories"][0]["wiz_category"] == "threat_center"
    assert intel["categories"][0]["label"] == "Threat Center (30d)"

    posture = client.get(
        "/metrics/security-posture?platform_pillar=threat-intel",
        headers=EXEC,
    ).json()
    assert len(posture["source_ratings"]) == 1
    assert posture["source_ratings"][0]["source"] == "wiz"
    assert posture["source_ratings"][0]["open_highs"] == 1


def test_platform_pillar_wiz_rating_scoped_to_wiz_teams(session, client) -> None:
    """Wiz rating on platform tab ignores findings owned by teams outside wiz_teams_for_pillar."""
    from sqlalchemy import update

    from app.core.models import Finding

    _make_n(session, "wiz", Severity.critical, 5, "wiz-order")
    session.execute(
        update(Finding)
        .where(Finding.native_id.like("wiz-order%"))
        .values(owner_team="order")
    )
    _make_n(session, "wiz", Severity.critical, 5, "wiz-pe")
    session.commit()

    ratings = {
        x["source"]: x
        for x in client.get(
            "/metrics/security-posture?platform_pillar=product&team=product-platform&team=order",
            headers=EXEC,
        ).json()["source_ratings"]
    }
    assert "wiz" in ratings
    # product-platform has no wiz rows — grade A; order-owned wiz drives the grade.
    assert ratings["wiz"]["open_criticals"] == 5


def test_platform_pillar_totals_match_asymmetric_source_cards(session, client) -> None:
    """Findings (open) on /platform must not count code-scanner rows on Wiz-only teams."""
    from sqlalchemy import update

    from app.core.models import Finding

    _make_n(session, "dependabot", Severity.critical, 12, "dep-order")
    session.execute(
        update(Finding)
        .where(Finding.native_id.like("dep-order%"))
        .values(owner_team="order")
    )
    _make_n(session, "wiz", Severity.high, 5, "wiz-order-tot")
    session.execute(
        update(Finding)
        .where(Finding.native_id.like("wiz-order-tot%"))
        .values(owner_team="order")
    )
    session.commit()

    qs = "platform_pillar=product&team=product-platform&team=order"
    data = client.get(f"/metrics/security-posture?{qs}", headers=EXEC).json()
    ratings = {r["source"]: r for r in data["source_ratings"]}
    assert ratings["dependabot"]["open_criticals"] == 0
    assert ratings["wiz"]["open_highs"] == 5
    assert data["open_criticals"] == 0
    assert data["open_highs"] == 5

    listed = client.get(f"/findings?{qs}", headers=EXEC).json()
    assert listed["total"] == 5

    trend = client.get(f"/metrics/trend?days=30&{qs}", headers=EXEC).json()
    today = date.today().isoformat()
    by_sev = {
        p["severity"]: p["open_count"]
        for p in trend["points"]
        if p["date"] == today
    }
    assert by_sev.get("critical", 0) == data["open_criticals"]
    assert by_sev.get("high", 0) == data["open_highs"]


def test_trend_latest_day_matches_posture_for_team_scope(session, client) -> None:
    """Developer/platform team scope: today's chart point matches the KPI boxes."""
    from sqlalchemy import update

    from app.core.models import Finding

    _make_n(session, "sonarcloud", Severity.critical, 2, "dev-trend-c")
    _make_n(session, "dependabot", Severity.high, 3, "dev-trend-h")
    session.execute(
        update(Finding)
        .where(Finding.native_id.like("dev-trend-%"))
        .values(owner_team="order")
    )
    session.commit()
    _seed_daily_metrics_for_trend(session)

    posture = client.get("/metrics/security-posture?team=order", headers=EXEC).json()
    trend = client.get("/metrics/trend?days=7&team=order", headers=EXEC).json()
    today = date.today().isoformat()
    by_sev = {
        p["severity"]: p["open_count"]
        for p in trend["points"]
        if p["date"] == today
    }
    assert by_sev.get("critical", 0) == posture["open_criticals"]
    assert by_sev.get("high", 0) == posture["open_highs"]


def test_source_ratings_respect_team_filter(session, client) -> None:
    """`?team=` narrows the per-source ratings the same way it narrows totals
    . A team with no findings is A even if the org is on fire."""
    _make_n(session, "sonarcloud", Severity.critical, 20, "team-other")
    # Override owner_team for the bulk to a different team so the filter narrows.
    from sqlalchemy import update

    from app.core.models import Finding
    session.execute(update(Finding).where(Finding.native_id.like("team-other%")).values(owner_team="legacy-translator"))
    session.commit()

    org = client.get("/metrics/security-posture", headers=EXEC).json()
    assert {x["source"]: x["grade"] for x in org["source_ratings"]}["sonarcloud"] == "D"

    scoped = client.get(
        "/metrics/security-posture?team=io-platform-eng", headers=EXEC
    ).json()
    assert {x["source"]: x["grade"] for x in scoped["source_ratings"]}["sonarcloud"] == "A"


def test_age_days_uses_upstream_created_at(session, client) -> None:
    """The /findings list should report age based on upstream timestamp, not ingest."""
    f = make_finding(
        session,
        native_id="age-check#1",
        severity=Severity.high,
        age_days=0.5,            # ingested 12h ago
        upstream_age_days=45,    # actually 45 days old upstream
        owner_team="pricing-platform",
    )
    session.commit()

    r = client.get(f"/findings/{f.id}", headers=EXEC)
    body = r.json()
    # Age should reflect upstream (~45d), not ingest (~0.5d).
    assert body["age_days"] > 40
    assert body["upstream_created_at"] is not None
    assert body["sla_started_at"] == body["upstream_created_at"]


# ---------------------------------------------------------------------------
# Executive-view momentum + ageing
#
# Three new exec-only signals on /metrics/summary, all reusing the same RBAC
# + `?team=` scope as the existing KPIs:
#
#   - new_critical_{7,30}d / closed_critical_{7,30}d
#       Burn-down counts on the FindingEvent log. Inflow = discovered ∪
#       reopened; outflow = fixed ∪ auto_closed. Nulled when observation
#       history is younger than the window (same honesty rule as WoW).
#
#   - age_buckets_open_crit_high
#       Open critical+high bucketed by `sla_started_at` age. Always present,
#       zeros when scope is empty (drives a horizontal stacked bar).
#
#   - oldest_open_critical_age_seconds
#       Max age of any open critical in scope. Null when no open crits.
# ---------------------------------------------------------------------------


def _record_event(
    session,
    finding,
    *,
    event_type: EventType,
    days_ago: float,
) -> None:
    """Append a typed event to a finding's event log at a given wall-clock offset.

    The factory only emits a `discovered` row at creation; the momentum tests
    need to seed closure / reopen events at deliberate offsets to exercise the
    7d / 30d windows.
    """
    occurred = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(
        FindingEvent(
            finding_id=finding.id,
            event_type=event_type,
            from_value="open",
            to_value=event_type.value,
            occurred_at=occurred,
            actor="system:test",
        )
    )


def test_summary_inflow_outflow_nulled_when_history_lt_7d(session, client) -> None:
    """A freshly-seeded DB nulls BOTH 7d and 30d momentum counts — same honesty
    rule that already nulls `open_criticals_wow_delta`. The frontend renders
    `history < 7d` / `history < 30d` from the null instead of misleading 0s."""
    make_finding(
        session,
        native_id="fresh-mom#1",
        severity=Severity.critical,
        age_days=2,
        upstream_age_days=400,
    )
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["new_critical_7d"] is None
    assert body["closed_critical_7d"] is None
    assert body["new_critical_30d"] is None
    assert body["closed_critical_30d"] is None


def test_summary_inflow_counts_discovered_and_reopened_in_window(session, client) -> None:
    """Inflow = `discovered` ∪ `reopened`. A re-introduced vulnerability is
    new risk on the books at exec level, so both event types feed the same
    count. The factory emits `discovered` on creation; we add a reopen event
    by hand to pin the union."""
    # Seed an old finding so the 7d observation history threshold is met.
    make_finding(
        session,
        native_id="aged-baseline#1",
        severity=Severity.critical,
        age_days=10,
        upstream_age_days=10,
    )

    # 2 fresh discoveries inside the 7d window. Factory backdates the
    # `discovered` event to `first_seen_at`, so `age_days < 7` puts them in
    # the window automatically.
    for i in range(2):
        make_finding(
            session,
            native_id=f"new-d#{i}",
            severity=Severity.critical,
            age_days=3,
            upstream_age_days=3,
        )
    # 1 reopen inside the 7d window — attach to an existing finding so it
    # doesn't double-count in the discovered total.
    reopened = make_finding(
        session,
        native_id="reopen-target#1",
        severity=Severity.critical,
        age_days=20,
        upstream_age_days=20,
    )
    _record_event(session, reopened, event_type=EventType.reopened, days_ago=2)
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    # 2 fresh discoveries (age_days=3) + 1 reopen = 3 inflow events.
    # The aged-baseline finding's `discovered` event is 10d old, outside the
    # 7d window — so it doesn't feed `new_critical_7d`.
    assert body["new_critical_7d"] == 3


def test_summary_outflow_counts_closures_in_window(session, client) -> None:
    """Outflow = `fixed` ∪ `auto_closed` events. `suppressed` is intentionally
    excluded — counting an out-of-policy escape hatch as "closed" would let
    suppression masquerade as remediation in the burn-down."""
    # Observation history >= 7d via an old finding.
    base = make_finding(
        session,
        native_id="closed-target#1",
        severity=Severity.critical,
        age_days=20,
        upstream_age_days=20,
    )
    _record_event(session, base, event_type=EventType.fixed, days_ago=3)

    auto = make_finding(
        session,
        native_id="closed-target#2",
        severity=Severity.critical,
        age_days=20,
        upstream_age_days=20,
    )
    _record_event(session, auto, event_type=EventType.auto_closed, days_ago=5)

    # `suppressed` MUST NOT count.
    suppressed = make_finding(
        session,
        native_id="suppressed#1",
        severity=Severity.critical,
        age_days=20,
        upstream_age_days=20,
    )
    _record_event(session, suppressed, event_type=EventType.suppressed, days_ago=2)
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["closed_critical_7d"] == 2  # fixed + auto_closed, NOT suppressed


def test_summary_outflow_only_counts_criticals(session, client) -> None:
    """Burn-down is a critical-specific signal — closing a high doesn't move
    the critical inflow/outflow numbers. Confirms the severity filter joins
    through to `Finding`."""
    high = make_finding(
        session,
        native_id="high-close#1",
        severity=Severity.high,
        age_days=20,
        upstream_age_days=20,
    )
    _record_event(session, high, event_type=EventType.fixed, days_ago=2)
    # And one aged baseline to unlock the 7d window.
    make_finding(
        session,
        native_id="baseline-crit#1",
        severity=Severity.critical,
        age_days=10,
        upstream_age_days=10,
    )
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["closed_critical_7d"] == 0


def test_summary_30d_window_includes_events_outside_7d(session, client) -> None:
    """The 30d window strictly contains the 7d window — an event 14d old
    counts toward 30d but not 7d. Pins the two windows as independent."""
    f = make_finding(
        session,
        native_id="mid-window#1",
        severity=Severity.critical,
        age_days=60,
        upstream_age_days=60,
    )
    _record_event(session, f, event_type=EventType.fixed, days_ago=14)
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["closed_critical_7d"] == 0
    assert body["closed_critical_30d"] == 1


def test_summary_momentum_respects_team_filter(session, client) -> None:
    """Momentum counts narrow with `?team=` (same as the rest of /summary).
    Two pillars closing criticals in parallel produce different numbers when
    each pillar's KPI strip is fetched independently."""
    a = make_finding(
        session,
        native_id="pa#1",
        severity=Severity.critical,
        age_days=20,
        owner_team="order",
    )
    _record_event(session, a, event_type=EventType.fixed, days_ago=3)
    b = make_finding(
        session,
        native_id="pb#1",
        severity=Severity.critical,
        age_days=20,
        owner_team="offer",
    )
    _record_event(session, b, event_type=EventType.fixed, days_ago=3)
    _record_event(session, b, event_type=EventType.fixed, days_ago=4)
    session.commit()

    order_body = client.get("/metrics/summary?team=order", headers=EXEC).json()
    offer_body = client.get("/metrics/summary?team=offer", headers=EXEC).json()
    assert order_body["closed_critical_7d"] == 1
    assert offer_body["closed_critical_7d"] == 2


def test_summary_momentum_team_filter_returns_requested_team(session, client) -> None:
    """`?team=` on the momentum fields is a pure query narrowing — any
    authenticated caller sees that team's inflow / outflow counts. The
    pre-collapse RBAC gate that returned zero for outsiders no longer
    exists (collapse)."""
    f = make_finding(
        session,
        native_id="rbac-mom#1",
        severity=Severity.critical,
        age_days=20,
        owner_team="io-platform-eng",
    )
    _record_event(session, f, event_type=EventType.fixed, days_ago=2)
    session.commit()

    alice = {
        "X-Dev-Identity": json.dumps(
            {"email": "alice@example.com", "google.groups": ["engineering@example.com"]}
        ),
    }
    body = client.get(
        "/metrics/summary?team=io-platform-eng", headers=alice
    ).json()
    assert body["closed_critical_7d"] == 1


def test_summary_age_buckets_partition_open_crit_high(session, client) -> None:
    """Each open critical+high lands in exactly one of four buckets, picked
    by `sla_started_at` age. The four buckets sum to the total open
    critical+high count in scope."""
    # One per bucket — boundaries are inclusive at the top.
    make_finding(session, native_id="b7#1", severity=Severity.critical, age_days=3, upstream_age_days=3)
    make_finding(session, native_id="b30#1", severity=Severity.high, age_days=20, upstream_age_days=20)
    make_finding(session, native_id="b90#1", severity=Severity.critical, age_days=60, upstream_age_days=60)
    make_finding(session, native_id="b90plus#1", severity=Severity.high, age_days=200, upstream_age_days=200)
    # A medium that MUST NOT be counted (buckets are crit+high only).
    make_finding(session, native_id="ignore#1", severity=Severity.medium, age_days=20, upstream_age_days=20)
    # And a closed critical that MUST NOT be counted.
    make_finding(
        session,
        native_id="closed#1",
        severity=Severity.critical,
        age_days=20,
        upstream_age_days=20,
        status=Status.auto_closed,
    )
    session.commit()

    buckets = client.get("/metrics/summary", headers=EXEC).json()[
        "age_buckets_open_crit_high"
    ]
    assert buckets == {"lte_7d": 1, "lte_30d": 1, "lte_90d": 1, "gt_90d": 1}


def test_summary_age_buckets_empty_when_scope_empty(session, client) -> None:
    """Buckets are never null — they zero out when the in-scope set is empty
    so the frontend can render the bar deterministically without a null
    check on every field."""
    buckets = client.get(
        "/metrics/summary?team=nonexistent-team", headers=EXEC
    ).json()["age_buckets_open_crit_high"]
    assert buckets == {"lte_7d": 0, "lte_30d": 0, "lte_90d": 0, "gt_90d": 0}


def test_summary_oldest_open_critical_age_returns_max_age(session, client) -> None:
    """Oldest = max(now - sla_started_at) across open criticals in scope.
    Confirms it's the *longest* age, not the most recent, and that it
    ignores highs."""
    make_finding(session, native_id="young#1", severity=Severity.critical, age_days=5, upstream_age_days=5)
    make_finding(session, native_id="middle#1", severity=Severity.critical, age_days=40, upstream_age_days=40)
    make_finding(session, native_id="ancient#1", severity=Severity.critical, age_days=200, upstream_age_days=200)
    # Highs and closed crits MUST NOT influence the answer.
    make_finding(session, native_id="ignore-high#1", severity=Severity.high, age_days=300, upstream_age_days=300)
    make_finding(
        session,
        native_id="ignore-closed#1",
        severity=Severity.critical,
        age_days=400,
        upstream_age_days=400,
        status=Status.auto_closed,
    )
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    oldest_days = body["oldest_open_critical_age_seconds"] / 86_400
    # ~200d, within rounding from `now`-based clock drift in the test process.
    assert 199 < oldest_days < 201


def test_summary_oldest_open_critical_null_when_none(session, client) -> None:
    """No open criticals -> null (not 0). The frontend renders "—"."""
    make_finding(session, native_id="just-high#1", severity=Severity.high, age_days=20)
    session.commit()

    body = client.get("/metrics/summary", headers=EXEC).json()
    assert body["oldest_open_critical_age_seconds"] is None


def test_summary_oldest_open_critical_narrows_with_team_filter(session, client) -> None:
    """Each pillar gets its own oldest-crit on the KPI strip — the filter
    applies before the max."""
    make_finding(
        session,
        native_id="order-old#1",
        severity=Severity.critical,
        age_days=300,
        upstream_age_days=300,
        owner_team="order",
    )
    make_finding(
        session,
        native_id="offer-new#1",
        severity=Severity.critical,
        age_days=10,
        upstream_age_days=10,
        owner_team="offer",
    )
    session.commit()

    order = client.get("/metrics/summary?team=order", headers=EXEC).json()
    offer = client.get("/metrics/summary?team=offer", headers=EXEC).json()
    assert order["oldest_open_critical_age_seconds"] / 86_400 > 290
    assert offer["oldest_open_critical_age_seconds"] / 86_400 < 15
