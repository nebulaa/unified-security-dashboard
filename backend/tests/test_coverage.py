"""Cloud security coverage — denominator honesty, RAG, blending, exceptions."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.coverage.collect import build_sample_snapshot
from app.coverage.compute import build_report
from app.coverage.config import parse_coverage_config
from app.coverage.model import CoverageSnapshot, HistoryPoint, InventoryItem
from app.coverage.store import SCHEMA_VERSION, from_dict, to_dict, write

NOW = datetime(2026, 9, 8, 6, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]

CONFIG_YAML = """
version: 1
thresholds:
  green_pct: 95
  amber_pct: 85
staleness_hours: 36
projects:
  product-offer-order:
    label: PRODUCT Offer & Order
    flagship: true
exceptions:
  - item_type: repo
    item_id: "repo:ExampleOrg/excepted"
    metric: "*"
    owner: security-team
    reason: Decommission in flight
    expires: "2099-01-01"
"""

HDR = {
    "X-Dev-Identity": json.dumps(
        {"email": "dev1@example.com", "google.groups": ["engineering@example.com"]}
    ),
}


def item(
    item_type: str,
    item_id: str,
    *,
    in_scope: bool = True,
    projects: tuple[str, ...] = (),
    signals: tuple[str, ...] = (),
) -> InventoryItem:
    return InventoryItem(
        item_type=item_type,
        item_id=item_id,
        display=item_id,
        in_scope=in_scope,
        projects=projects,
        signals=frozenset(signals),
    )


def repo(name: str, *, covered: bool, **kwargs) -> InventoryItem:
    return item(
        "repo",
        f"repo:ExampleOrg/{name}",
        signals=("sonar_analyzed_30d",) if covered else (),
        **kwargs,
    )


def metric_by_key(report, key: str):
    for layer in report.layers:
        for metric in layer.metrics:
            if metric.key == key:
                return metric
    raise AssertionError(f"metric {key} not in report")


def cell_by_metric(row, metric: str):
    for cell in row.cells:
        if cell.metric == metric:
            return cell
    raise AssertionError(f"cell {metric} not in project row")


def config():
    return parse_coverage_config(CONFIG_YAML)


def shipped_config():
    """The real `config/coverage.yaml` — the sample data is built against it."""
    return parse_coverage_config(
        (REPO_ROOT / "config" / "coverage.yaml").read_text(encoding="utf-8")
    )


def report_for(items, **kwargs):
    snapshot = CoverageSnapshot(as_of=NOW, items=tuple(items), **kwargs)
    return build_report(snapshot, config(), now=NOW)


def test_exception_leaves_denominator_and_stays_visible() -> None:
    """The excepted repo is uncovered; it must not be counted as covered either."""
    report = report_for(
        [
            repo("a", covered=True),
            repo("b", covered=True),
            repo("excepted", covered=False),
        ]
    )

    sonar = metric_by_key(report, "sonar")
    assert (sonar.ratio.covered, sonar.ratio.in_scope) == (2, 2)
    assert sonar.ratio.excepted == 1
    assert sonar.ratio.pct == 100.0
    assert "repo:ExampleOrg/excepted" not in sonar.gap_items


def test_expired_exception_returns_to_denominator() -> None:
    cfg = parse_coverage_config(
        CONFIG_YAML.replace('expires: "2099-01-01"', 'expires: "2000-01-01"')
    )
    snapshot = CoverageSnapshot(
        as_of=NOW,
        items=(repo("a", covered=True), repo("excepted", covered=False)),
    )

    sonar = metric_by_key(build_report(snapshot, cfg, now=NOW), "sonar")
    assert (sonar.ratio.covered, sonar.ratio.in_scope, sonar.ratio.excepted) == (1, 2, 0)
    assert sonar.ratio.pct == 50.0


def test_out_of_scope_items_are_not_in_the_denominator() -> None:
    report = report_for(
        [repo("active", covered=True), repo("archived", covered=False, in_scope=False)]
    )

    sonar = metric_by_key(report, "sonar")
    assert (sonar.ratio.covered, sonar.ratio.in_scope) == (1, 1)


def test_empty_denominator_reports_na_not_full_coverage() -> None:
    """No in-scope EC2/GCE estate is not 100% VM coverage."""
    report = report_for([repo("a", covered=True)])

    vm = metric_by_key(report, "runtime_vm")
    assert vm.ratio.in_scope == 0
    assert vm.ratio.pct is None
    assert vm.rag == "na"


def test_failed_required_source_makes_metric_unavailable_not_red() -> None:
    snapshot = CoverageSnapshot(
        as_of=NOW,
        items=(repo("a", covered=True),),
        degraded_sources=("sonar",),
    )

    sonar = metric_by_key(build_report(snapshot, config(), now=NOW), "sonar")
    assert sonar.ratio.pct == 100.0  # partial ratio retained for diagnostics
    assert sonar.rag == "na"
    assert sonar.unavailable_sources == ("sonar",)
    assert sonar.trend == ()


@pytest.mark.parametrize(
    ("covered", "total", "expected"),
    [(95, 100, "green"), (94, 100, "amber"), (85, 100, "amber"), (84, 100, "red")],
)
def test_rag_thresholds(covered: int, total: int, expected: str) -> None:
    items = [repo(f"r{i}", covered=i < covered) for i in range(total)]

    assert metric_by_key(report_for(items), "sonar").rag == expected


def test_all_environments_secondary_divides_by_every_account() -> None:
    """The Wiz secondary is the only figure allowed to count non-prod accounts."""
    items = [
        item("cloud_account", "gcp:prod-1", signals=("wiz_connector",)),
        item("cloud_account", "gcp:stg-1", in_scope=False, signals=("wiz_connector",)),
        item("cloud_account", "gcp:stg-2", in_scope=False),
    ]

    wiz = metric_by_key(report_for(items), "wiz_connector")
    assert (wiz.ratio.covered, wiz.ratio.in_scope) == (1, 1)
    assert wiz.secondary is not None
    assert (wiz.secondary.ratio.covered, wiz.secondary.ratio.in_scope) == (2, 3)


def test_project_runtime_cell_is_weighted_and_keeps_both_ratios() -> None:
    items = [
        item("cluster", "gke:product-1", projects=("product-offer-order",), signals=("runtime_sensor_7d",)),
        item("cluster", "gke:product-2", projects=("product-offer-order",)),
        *[
            item(
                "vm",
                f"gce:product-{i}",
                projects=("product-offer-order",),
                signals=("runtime_sensor_reporting",),
            )
            for i in range(8)
        ],
    ]

    cell = cell_by_metric(report_for(items).projects[0], "runtime")
    assert (cell.ratio.covered, cell.ratio.in_scope) == (9, 10)
    assert cell.ratio.pct == 90.0
    assert cell.note == "clusters 1 / 2 · instances 8 / 8"


def test_project_runtime_cell_omits_a_side_with_no_estate() -> None:
    items = [
        item("cluster", "gke:product-1", projects=("product-offer-order",), signals=("runtime_sensor_7d",)),
    ]

    cell = cell_by_metric(report_for(items).projects[0], "runtime")
    assert cell.ratio.pct == 100.0
    assert cell.note == "clusters 1 / 1"


def test_project_row_ignores_items_outside_the_project() -> None:
    items = [
        repo("product-1", covered=True, projects=("product-offer-order",)),
        repo("other-1", covered=False),
    ]

    row = report_for(items).projects[0]
    sonar = cell_by_metric(row, "sonar")
    assert (sonar.ratio.covered, sonar.ratio.in_scope) == (1, 1)
    assert sonar.note == "1 / 1 repos"


def test_unmapped_counts_stay_in_the_org_figures() -> None:
    items = [
        repo("product-1", covered=True, projects=("product-offer-order",)),
        repo("orphan-1", covered=True),
        item("cloud_account", "gcp:orphan", signals=("wiz_connector",)),
    ]

    report = report_for(items)
    assert report.unmapped.repos == 1
    assert report.unmapped.cloud_accounts == 1
    assert metric_by_key(report, "sonar").ratio.in_scope == 2


def test_enabled_layers_can_hide_cloud_metrics() -> None:
    cfg = parse_coverage_config(CONFIG_YAML + "\nenabled_layers: [code]\n")
    items = [
        repo("product-1", covered=True, projects=("product-offer-order",)),
        item("cloud_account", "gcp:prod", signals=("wiz_connector",)),
    ]
    report = build_report(
        CoverageSnapshot(as_of=NOW, items=tuple(items)), cfg, now=NOW
    )
    assert [layer.key for layer in report.layers] == ["code"]
    assert [cell.metric for cell in report.projects[0].cells] == ["sonar", "dependabot"]
    assert report.unmapped.cloud_accounts == 0


def test_month_on_month_delta_uses_a_full_window() -> None:
    items = [repo("a", covered=True)]
    history = (
        HistoryPoint(day=date(2026, 8, 9), pct={"sonar": 80.0}),
        HistoryPoint(day=date(2026, 9, 8), pct={"sonar": 100.0}),
    )

    sonar = metric_by_key(report_for(items, history=history), "sonar")
    assert sonar.delta_pts == 20.0
    assert sonar.trend == (80.0, 100.0)


def test_delta_is_withheld_when_history_is_shorter_than_the_window() -> None:
    """A 3-day-old series must not be presented as a month-on-month movement."""
    items = [repo("a", covered=True)]
    history = (
        HistoryPoint(day=date(2026, 9, 5), pct={"sonar": 90.0}),
        HistoryPoint(day=date(2026, 9, 8), pct={"sonar": 100.0}),
    )

    sonar = metric_by_key(report_for(items, history=history), "sonar")
    assert sonar.delta_pts is None
    assert sonar.trend == (90.0, 100.0)


def test_snapshot_ages_into_stale() -> None:
    fresh = CoverageSnapshot(as_of=NOW - timedelta(hours=12), items=(repo("a", covered=True),))
    old = CoverageSnapshot(as_of=NOW - timedelta(hours=48), items=(repo("a", covered=True),))

    assert build_report(fresh, config(), now=NOW).stale is False
    assert build_report(old, config(), now=NOW).stale is True


def test_snapshot_survives_a_json_round_trip() -> None:
    snapshot = CoverageSnapshot(
        as_of=NOW,
        items=(repo("a", covered=True, projects=("product-offer-order",)),),
        history=(HistoryPoint(day=date(2026, 9, 8), pct={"sonar": 100.0}),),
        degraded_sources=("wiz",),
    )

    restored = from_dict(json.loads(json.dumps(to_dict(snapshot))))
    assert restored == snapshot


def test_snapshot_rejects_an_unknown_schema_version() -> None:
    raw = to_dict(CoverageSnapshot(as_of=NOW))
    raw["schema_version"] = SCHEMA_VERSION + 1

    with pytest.raises(ValueError, match="re-run the collector"):
        from_dict(raw)


def test_sample_snapshot_is_internally_consistent() -> None:
    """The local prototype data must obey the same rules as a real collection."""
    cfg = shipped_config()
    report = build_report(build_sample_snapshot(NOW, cfg), cfg, now=NOW)

    sonar = metric_by_key(report, "sonar")
    # Shipped config has no real exceptions yet: all 239 eligible sample repos
    # remain in Y. The exception mechanics are tested independently above.
    assert sonar.ratio.in_scope == 239
    assert sonar.ratio.excepted == 0
    assert sonar.ratio.covered == 212
    assert sonar.ratio.gaps == 27
    assert sonar.rag == "amber"
    assert [layer.key for layer in report.layers] == ["code"]

    product = report.projects[0]
    assert product.flagship is True
    assert [cell.metric for cell in product.cells] == ["sonar", "dependabot"]


def test_sample_history_reproduces_the_configured_month_delta() -> None:
    cfg = shipped_config()
    report = build_report(build_sample_snapshot(NOW, cfg), cfg, now=NOW)

    assert metric_by_key(report, "sonar").delta_pts == pytest.approx(3.0, abs=0.2)
    assert metric_by_key(report, "dependabot").delta_pts == pytest.approx(1.0, abs=0.2)


def test_coverage_endpoint_serves_the_written_snapshot(session, tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    path = tmp_path / "latest.json"
    write(build_sample_snapshot(datetime.now(UTC)), path)
    monkeypatch.setattr(get_settings(), "coverage_snapshot_path", str(path))

    body = TestClient(create_app()).get("/metrics/coverage", headers=HDR)
    assert body.status_code == 200
    payload = body.json()

    assert [layer["key"] for layer in payload["layers"]] == ["platform", "workload", "code"]
    assert payload["projects"][0]["key"] == "product-offer-order"
    assert payload["stale"] is False


def test_coverage_endpoint_explains_a_missing_snapshot(session, tmp_path, monkeypatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "coverage_snapshot_path", str(tmp_path / "absent.json"))

    response = TestClient(create_app()).get("/metrics/coverage", headers=HDR)
    assert response.status_code == 503
    assert "coverage-sample" in response.json()["detail"]
