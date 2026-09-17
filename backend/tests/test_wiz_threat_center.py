"""Wiz Threat Center fetch helpers."""

from __future__ import annotations

from app.core.wiz_threat_center_fetch import (
    count_threat_impact,
    translate_threat_link_filter,
)


def test_translate_vulnerability_link_filter() -> None:
    raw = {
        "status": {"equals": ["OPEN"]},
        "vulnerabilityExternalId": {"equals": ["CVE-2026-45618"]},
    }
    out = translate_threat_link_filter("VULNERABILITY_FINDINGS", raw)
    assert out == {
        "status": ["OPEN"],
        "vulnerabilityExternalIdV2": {"equals": ["CVE-2026-45618"]},
    }


def test_translate_detection_link_filter() -> None:
    raw = {
        "sourceRule": {"equals": ["cer-github-data-massCloneOperationsByUser"]},
        "status": {"equals": ["OPEN", "IN_PROGRESS"]},
    }
    out = translate_threat_link_filter("THREATS", raw)
    assert out["matchedRule"] == [{"id": "cer-github-data-massCloneOperationsByUser"}]
    assert out["status"] == {"equals": ["OPEN", "IN_PROGRESS"]}


def test_count_threat_impact_sums_breakdown(monkeypatch) -> None:
    from app.core import wiz_threat_center_fetch as mod

    calls: list[tuple[str, dict]] = []

    def fake_count(*, root, filter_by, **kwargs):
        calls.append((root, filter_by))
        if root == "detections" and "advisory" in filter_by:
            return 0
        if root == "vulnerabilityFindings":
            return 2
        return 0

    monkeypatch.setattr(mod, "_count_with_filter", fake_count)
    total, breakdown = count_threat_impact(
        api_url="https://example/graphql",
        token="tok",
        threat_id="wiz-adv-2026-094",
        finding_links=[
            {
                "type": "VULNERABILITY_FINDINGS",
                "filters": {
                    "status": {"equals": ["OPEN"]},
                    "vulnerabilityExternalId": {"equals": ["CVE-2026-45618"]},
                },
            }
        ],
        client=None,  # type: ignore[arg-type]
    )
    assert total == 2
    assert breakdown == {"VULNERABILITY_FINDINGS": 2}
