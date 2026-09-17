"""Pin the Dependabot native_id format and severity mapping."""

from __future__ import annotations

from app.normalizer.mappers.dependabot import map_alert, native_id_for_alert


def _alert(
    full_name: str = "ExampleOrg/example-service",
    number: int = 42,
    severity: str = "high",
    cve_id: str | None = "CVE-2024-12345",
    cwe_ids: list[str] | None = None,
    summary: str = "Use after free in libxml2",
    description: str = "Long description...",
    package_name: str = "libxml2",
    created_at: str | None = "2025-09-01T12:34:56Z",
) -> dict:
    payload = {
        "number": number,
        "state": "open",
        "repository": {"full_name": full_name},
        "security_advisory": {
            "severity": severity,
            "summary": summary,
            "description": description,
            "cve_id": cve_id,
            "cwe_ids": cwe_ids or [],
        },
        "dependency": {"package": {"ecosystem": "pip", "name": package_name}},
    }
    if created_at is not None:
        payload["created_at"] = created_at
    return payload


def test_native_id_format() -> None:
    assert native_id_for_alert(_alert()) == "ExampleOrg/example-service#42"


def test_finding_id_is_deterministic() -> None:
    a = map_alert(_alert())
    b = map_alert(_alert())
    assert a.id == b.id


def test_finding_id_differs_per_alert_number() -> None:
    a = map_alert(_alert(number=42))
    b = map_alert(_alert(number=43))
    assert a.id != b.id


def test_correlation_group_only_when_cve_present() -> None:
    with_cve = map_alert(_alert(cve_id="CVE-2024-12345"))
    without_cve = map_alert(_alert(cve_id=None))
    assert with_cve.correlation_group_id is not None
    assert without_cve.correlation_group_id is None


def test_severity_mapping_includes_moderate() -> None:
    assert map_alert(_alert(severity="moderate")).severity.value == "medium"
    assert map_alert(_alert(severity="critical")).severity.value == "critical"
    assert map_alert(_alert(severity="high")).severity.value == "high"
    assert map_alert(_alert(severity="low")).severity.value == "low"


def test_asset_fields() -> None:
    f = map_alert(_alert(full_name="ExampleOrg/svc"))
    assert f.asset_id == "repo:ExampleOrg/svc"
    assert f.asset_root == "repo:ExampleOrg/svc"
    assert f.asset_type == "github_repo"
    assert f.asset_display == "ExampleOrg/svc"


def test_upstream_created_at_parsed_from_iso8601() -> None:
    # GitHub returns RFC 3339 with `Z` suffix; we must turn that into a tz-aware datetime.
    f = map_alert(_alert(created_at="2025-09-01T12:34:56Z"))
    assert f.upstream_created_at is not None
    assert f.upstream_created_at.tzinfo is not None
    assert f.upstream_created_at.year == 2025
    assert f.upstream_created_at.month == 9


def test_upstream_created_at_missing_is_none() -> None:
    # Defensive: legacy GitHub responses or malformed payloads must not crash the mapper.
    f = map_alert(_alert(created_at=None))
    assert f.upstream_created_at is None
