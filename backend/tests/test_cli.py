"""Smoke tests for the secdb CLI.

The pre-collapse `roles {grant,revoke,list}` subcommand group is retired —
admin status lives in `config/rbac.yaml.admin_emails` and is a YAML edit,
not a CLI operation. Tests covering that group have been removed; what
remains pins the operator gap-triage commands (ownership validate, scanner
status, backfill stub).
"""

from __future__ import annotations

from click.testing import CliRunner

from app.cli.main import cli


def test_ownership_validate(session) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["ownership", "validate"])
    assert r.exit_code == 0, r.output
    assert "OK" in r.output


def test_scanner_status_lists_all_known_sources(session) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["scanner", "status"])
    assert r.exit_code == 0, r.output
    for source in ("dependabot", "wiz", "trivy", "nuclei", "vanta", "sonarcloud", "pentest"):
        assert source in r.output


def test_backfill_is_a_stub(session) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["backfill", "--source", "dependabot"])
    assert r.exit_code == 2
    assert "not implemented" in r.output
