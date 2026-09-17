"""Tests for rollup --status diagnostics."""

from __future__ import annotations

from datetime import date, timedelta

from app.core.enums import Severity
from app.jobs.rollup import print_status
from tests._factory import make_finding


def test_print_status_reports_findings_and_metrics(session, capsys) -> None:
    make_finding(session, native_id="status#1", severity=Severity.critical)
    session.commit()
    target = date.today() - timedelta(days=1)
    from app.jobs.rollup import rollup_date

    rollup_date(session, target)
    session.commit()

    print_status(session)
    out = capsys.readouterr().out
    assert "findings total=1" in out
    assert "daily_metrics rows=" in out
