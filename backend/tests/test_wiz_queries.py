"""Wiz poller query filters."""

from app.pollers.wiz_queries import (
    DEPRECATED_DETECTORS,
    SCHEDULED_DETECTORS,
    _vuln_filter,
)


def test_scheduled_detectors_exclude_secrets_and_code() -> None:
    names = {d.name for d in SCHEDULED_DETECTORS}
    assert names == {"issues", "vulnerability_findings", "cloud_config"}
    deprecated = {d.name for d in DEPRECATED_DETECTORS}
    assert deprecated == {"secrets", "code"}


def test_vuln_filter_requires_kev_and_exploit() -> None:
    filt = _vuln_filter(backfill=False, backfill_after=None)
    assert filt["hasCisaKevExploit"] is True
    assert filt["hasExploit"] is True
    assert "validatedInRuntime" not in filt
    assert filt["vendorSeverity"] == ["CRITICAL", "HIGH"]
