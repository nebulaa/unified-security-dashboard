"""Helpers for /executive cross-section metric alignment tests.

The executive view renders the same pillar scope from several endpoints
(see `frontend/app/executive/page.tsx`). These helpers fetch that bundle and
assert the open critical / high numbers reconcile across every section.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

EXEC_HEADERS = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


def exec_scope_query(
    *teams: str,
    platform_wiz_issues_only: bool = True,
    trend_days: int = 90,
) -> str:
    """Build the same query string the executive page uses for a pillar rollup."""
    params: list[str] = [f"team={t}" for t in teams]
    if platform_wiz_issues_only:
        params.append("platform_wiz_issues_only=true")
    return "&".join(params)


def fetch_exec_metrics_bundle(
    client: TestClient,
    qs: str,
    *,
    trend_days: int = 90,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch every metrics endpoint the executive view uses for one pillar."""
    hdrs = headers or EXEC_HEADERS
    return {
        "posture": client.get(
            f"/metrics/security-posture?{qs}", headers=hdrs
        ).json(),
        "summary": client.get(f"/metrics/summary?{qs}", headers=hdrs).json(),
        "trend": client.get(
            f"/metrics/trend?days={trend_days}&{qs}", headers=hdrs
        ).json(),
        "top_teams": client.get(
            f"/metrics/top-teams?limit=50&{qs}", headers=hdrs
        ).json(),
        "top_services": client.get(
            f"/metrics/top-services?limit=200&{qs}", headers=hdrs
        ).json(),
    }


def trend_latest_crit_high(trend: dict[str, Any]) -> tuple[int, int]:
    """Return open critical + high counts on the trend chart's latest day."""
    points = trend.get("points") or []
    if not points:
        return 0, 0
    latest_date = max(p["date"] for p in points)
    crit = high = 0
    for point in points:
        if point["date"] != latest_date:
            continue
        if point["severity"] == "critical":
            crit = point["open_count"]
        elif point["severity"] == "high":
            high = point["open_count"]
    return crit, high


def assert_exec_metrics_aligned(bundle: dict[str, Any]) -> None:
    """Every exec section showing open crit/high must match the pillar badge."""
    posture = bundle["posture"]
    summary = bundle["summary"]
    trend = bundle["trend"]

    crit = posture["open_criticals"]
    high = posture["open_highs"]
    total = crit + high

    assert summary["open_criticals"] == crit, (
        "KPI strip open criticals != pillar badge "
        f"({summary['open_criticals']} vs {crit})"
    )

    buckets = summary["age_buckets_open_crit_high"]
    bucket_total = sum(buckets.values())
    assert bucket_total == total, (
        "Age distribution total != pillar badge crit+high "
        f"({bucket_total} vs {total})"
    )

    team_crit = sum(row["open_criticals"] for row in bundle["top_teams"])
    team_high = sum(row["open_highs"] for row in bundle["top_teams"])
    assert team_crit == crit, (
        "Offender list (by team) critical sum != pillar badge "
        f"({team_crit} vs {crit})"
    )
    assert team_high == high, (
        "Offender list (by team) high sum != pillar badge "
        f"({team_high} vs {high})"
    )

    svc_crit = sum(row["open_criticals"] for row in bundle["top_services"])
    svc_high = sum(row["open_highs"] for row in bundle["top_services"])
    assert svc_crit == crit, (
        "Offender list (by service) critical sum != pillar badge "
        f"({svc_crit} vs {crit})"
    )
    assert svc_high == high, (
        "Offender list (by service) high sum != pillar badge "
        f"({svc_high} vs {high})"
    )

    trend_crit, trend_high = trend_latest_crit_high(trend)
    assert trend_crit == crit, (
        "Trend chart latest critical != pillar badge "
        f"({trend_crit} vs {crit})"
    )
    assert trend_high == high, (
        "Trend chart latest high != pillar badge "
        f"({trend_high} vs {high})"
    )
