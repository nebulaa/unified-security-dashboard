"""Pin the SonarCloud native_id format, severity table, and asset resolution
.

The mapper accepts an explicit `sonar_key_to_asset_id` override map so these tests
don't depend on whatever the test-fixture `ownership.yaml` happens to declare. The
real production map is sourced from `OwnershipMap.sonar_key_to_asset_id` by
`map_snapshot`, exercised separately in `test_sonarcloud_mapper_snapshot_uses_overrides`.
"""

from __future__ import annotations

from typing import Any

from app.core.enums import Severity
from app.normalizer.mappers.sonarcloud import (
    SONARCLOUD_SOURCE,
    SONARCLOUD_TRIVY_SOURCE,
    map_issue,
    native_id_for_issue,
)

ORG = "exampleorg"


def _issue(
    *,
    key: str = "AYxxxxxxxxxxxx-1",
    project: str = "exampleorg_product-core",
    severity: str = "BLOCKER",
    message: str = "Make sure this regex is intended.",
    rule: str | None = "java:S2076",
    tags: list[str] | None = None,
    component: str | None = "exampleorg_product-core:src/Main.java",
    creation_date: str | None = "2025-09-01T12:34:56+0000",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": key,
        "project": project,
        "severity": severity,
        "message": message,
    }
    if rule is not None:
        payload["rule"] = rule
    if tags is not None:
        payload["tags"] = tags
    if component is not None:
        payload["component"] = component
    if creation_date is not None:
        payload["creationDate"] = creation_date
    return payload


def _map(issue: dict[str, Any], **overrides):
    return map_issue(issue, organization=ORG, sonar_key_to_asset_id=overrides.pop("overrides", {}))


def test_native_id_format() -> None:
    assert (
        native_id_for_issue(ORG, _issue(key="AY-1", project="exampleorg_product-core"))
        == "exampleorg/exampleorg_product-core#AY-1"
    )


def test_finding_id_is_deterministic() -> None:
    a = _map(_issue())
    b = _map(_issue())
    assert a.id == b.id
    assert a.source == SONARCLOUD_SOURCE


def test_finding_id_differs_per_issue_key() -> None:
    a = _map(_issue(key="AY-1"))
    b = _map(_issue(key="AY-2"))
    assert a.id != b.id


def test_severity_table_blocker_to_critical() -> None:
    """BLOCKER → critical (the only Sonar severity that becomes our
    headline KPI). Pinning this keeps "Open criticals" honest."""
    assert _map(_issue(severity="BLOCKER")).severity is Severity.critical


def test_severity_table_critical_to_high() -> None:
    """Sonar's CRITICAL is conservative; mapping it to our `critical`
    would inflate the KPI. Demoted to high."""
    assert _map(_issue(severity="CRITICAL")).severity is Severity.high


def test_severity_table_major_to_medium() -> None:
    assert _map(_issue(severity="MAJOR")).severity is Severity.medium


def test_severity_table_minor_to_low() -> None:
    assert _map(_issue(severity="MINOR")).severity is Severity.low


def test_severity_table_info_to_info() -> None:
    assert _map(_issue(severity="INFO")).severity is Severity.info


def test_severity_unknown_falls_back_to_info() -> None:
    """Defensive: if Sonar adds a new severity tier, we want the row to land,
    not crash the whole snapshot."""
    assert _map(_issue(severity="ULTRA")).severity is Severity.info


def test_asset_resolution_via_convention(monkeypatch) -> None:
    """Default convention: `{org_lower}_{repo}` → `repo:{github_org}/{repo}`.

    No YAML override needed when SonarCloud was set up by the auto-import flow,
    which produces this exact key shape. Verified end-to-end against
    exampleorg_product-core in S4.

    `GITHUB_ORG` is required for the convention path — see
    `_resolve_asset_id` for the why. Set it explicitly here so we pin the
    canonical mixed-case asset_id rather than asserting only on the suffix.
    """
    from app.core import config as cfg_mod

    monkeypatch.setenv("GITHUB_ORG", "ExampleOrg")
    cfg_mod.reset_settings_for_tests()

    f = _map(_issue(project="exampleorg_product-core"))
    assert f.asset_id == "repo:ExampleOrg/product-core"
    assert f.asset_display == "ExampleOrg/product-core"
    assert f.asset_type == "github_repo"
    assert f.asset_root == f.asset_id

    cfg_mod.reset_settings_for_tests()


def test_asset_resolution_via_explicit_override() -> None:
    """`ownership.yaml.assets[*].sonar_project_key` wins over the convention.

    Required when the Sonar key doesn't follow `{org}_{repo}` (custom imports,
    legacy projects, monorepos with `branch.module` keys, etc.)."""
    overrides = {"weird_legacy_key": "repo:ExampleOrg/legacy-svc"}
    f = map_issue(
        _issue(project="weird_legacy_key"),
        organization=ORG,
        sonar_key_to_asset_id=overrides,
    )
    assert f.asset_id == "repo:ExampleOrg/legacy-svc"
    assert f.asset_display == "ExampleOrg/legacy-svc"
    assert f.asset_type == "github_repo"


def test_asset_resolution_sonarproj_override() -> None:
    """Multi-org Retail API split: a single
    GitHub repo (retail-api) hosts three Sonar projects in the `exampledivision`
    org, each owned by a different team. The override map points each Sonar
    project at a synthetic `sonarproj:` asset_id; the display strips the
    namespace prefix so the dev-view component map can render it as the
    service label ("ExampleOrg.Commerce.Orders.API" -> "Orders API")."""
    overrides = {"ExampleOrg.Commerce.Orders.API": "sonarproj:ExampleOrg.Commerce.Orders.API"}
    f = map_issue(
        _issue(project="ExampleOrg.Commerce.Orders.API"),
        organization="exampledivision",
        sonar_key_to_asset_id=overrides,
    )
    assert f.asset_id == "sonarproj:ExampleOrg.Commerce.Orders.API"
    assert f.asset_display == "ExampleOrg.Commerce.Orders.API"  # prefix stripped
    assert f.asset_type == "sonarcloud_project"
    # native_id still carries the org so the same Sonar key across two orgs
    # (unlikely but possible) wouldn't collide.
    assert f.native_id == "exampledivision/ExampleOrg.Commerce.Orders.API#AYxxxxxxxxxxxx-1"


def test_asset_resolution_convention_handles_exampledivision(monkeypatch) -> None:
    """The convention path is org-aware — for an `exampledivision`-org project that
    happens to follow the `{org}_{repo}` shape, it'd still resolve. (None of
    today's exampledivision projects follow that shape, but the path must be
    symmetric across orgs since the mapper takes org as a parameter.)

    The convention path uses whatever GitHub org is configured via
    `GITHUB_ORG` — at ExampleOrg today there's a single `GITHUB_ORG=ExampleOrg`,
    and the multi-org Retail API split is handled via `sonar_project_key`
    overrides rather than the convention path. Pin the transform here by
    setting GITHUB_ORG explicitly.
    """
    from app.core import config as cfg_mod

    monkeypatch.setenv("GITHUB_ORG", "exampledivision")
    cfg_mod.reset_settings_for_tests()

    f = map_issue(
        _issue(project="exampledivision_some-repo", component=None),
        organization="exampledivision",
        sonar_key_to_asset_id={},
    )
    assert f.asset_id == "repo:exampledivision/some-repo"
    assert f.asset_type == "github_repo"

    cfg_mod.reset_settings_for_tests()


def test_asset_resolution_convention_falls_through_when_github_org_unset(monkeypatch) -> None:
    """Hardening: when `GITHUB_ORG` is empty, the convention path refuses
    to synthesise a `repo:{organization}/...` asset_id from the lowercase
    SonarCloud org and falls through to the project-key escape valve
    (`repo:{project_key}`) instead.

    This pins the failure mode that produced the `example-service` see-saw in
    cloud: SonarCloud rows ingested with `GITHUB_ORG=""` got
    `repo:exampleorg/example-service` (lowercase), which never matched
    `ownership.yaml.assets[*].id = repo:ExampleOrg/example-service` exactly, read
    back as `unowned`, and were flipped back to `unowned` by the rollup
    re-resolve on every pass. With this fallthrough, the same misconfig
    now produces `repo:exampleorg_product-core` (no slash) — clearly broken on
    /admin, and impossible to confuse with a canonical asset_id. The
    `validate-config` CI gate further fails closed on cloud deploys when
    `GITHUB_ORG` is empty so this path is only reachable in dev/test.
    """
    from app.core import config as cfg_mod

    # `setenv("", "")` (not `delenv`) — pydantic-settings reads `.env.local`
    # which carries `GITHUB_ORG=ExampleOrg` for dev. Env vars take precedence
    # over dotenv files, so the empty-string override is what actually
    # exercises the unset codepath.
    monkeypatch.setenv("GITHUB_ORG", "")
    cfg_mod.reset_settings_for_tests()

    f = _map(_issue(project="exampleorg_product-core"))
    assert f.asset_id == "repo:exampleorg_product-core"
    assert f.asset_display == "exampleorg_product-core"
    assert f.asset_type == "github_repo"

    cfg_mod.reset_settings_for_tests()


def test_asset_resolution_unmapped_falls_through() -> None:
    """A key that matches neither override nor convention lands as `repo:{key}`.

    The processor will stamp it `unowned`. This is the intended escape valve —
    findings appear, the admin sees the gap on `/admin`, and they're triaged
    by adding a YAML entry rather than silently dropped."""
    f = _map(_issue(project="someone-elses-project"))
    assert f.asset_id == "repo:someone-elses-project"


def test_cwe_extracted_from_tags() -> None:
    """SonarCloud puts CWE refs in `tags` like ['cwe:cwe-79', 'owasp-a3']."""
    f = _map(_issue(tags=["cwe:cwe-79", "owasp-a3", "java"]))
    assert f.cwe_id == "CWE-79"


def test_cwe_absent_when_no_cwe_tag() -> None:
    f = _map(_issue(tags=["owasp-a3", "java"]))
    assert f.cwe_id is None


def test_upstream_created_at_parsed_from_sonar_format() -> None:
    """Sonar emits `+0000` (no colon). 3.13 fromisoformat handles it; we normalise
    defensively for older patch releases."""
    f = _map(_issue(creation_date="2025-09-01T12:34:56+0000"))
    assert f.upstream_created_at is not None
    assert f.upstream_created_at.tzinfo is not None
    assert f.upstream_created_at.year == 2025
    assert f.upstream_created_at.month == 9


def test_upstream_created_at_missing_is_none() -> None:
    f = _map(_issue(creation_date=None))
    assert f.upstream_created_at is None


def test_rule_appended_to_description_and_tags() -> None:
    f = _map(_issue(rule="java:S2076"))
    assert "rule: java:S2076" in f.description
    assert "rule:java:S2076" in f.tags


def test_file_location_added_to_tags_when_component_present() -> None:
    f = _map(_issue(component="exampleorg_product-core:src/Main.java"))
    assert any(t.startswith("file:src/Main.java") for t in f.tags)


def test_no_correlation_group_for_sonar_issues() -> None:
    """Sonar issues are rule-based; we deliberately don't fabricate a CVE-style
    correlation key. If/when Sonar starts annotating with CVE refs reliably,
    revisit."""
    assert _map(_issue()).correlation_group_id is None
    assert _map(_issue()).cve_id is None


def test_map_snapshot_applies_organization_and_overrides(monkeypatch) -> None:
    """End-to-end: `map_snapshot` reads the override map from the cached
    `OwnershipMap` and propagates `organization` from the envelope."""
    from app.normalizer.mappers import sonarcloud as mod

    class _FakeOwnership:
        sonar_key_to_asset_id = {"exampleorg_product-core": "repo:ExampleOrg/product-core"}

    class _FakeCache:
        def get_ownership(self):
            return _FakeOwnership()

    monkeypatch.setattr(mod, "get_config_cache", lambda: _FakeCache())

    payload = {"organization": "exampleorg", "issues": [_issue(project="exampleorg_product-core")]}
    out = mod.map_snapshot(payload)
    assert len(out) == 1
    assert out[0].asset_id == "repo:ExampleOrg/product-core"  # override beats convention
    assert out[0].native_id.startswith("exampleorg/exampleorg_product-core#")


def test_external_trivy_rule_routes_to_sonarcloud_trivy_source() -> None:
    """SonarCloud lets teams import third-party scanner reports as "external
    issues"; those carry rules of the form `external_<engineId>:<ruleId>` per
    Sonar's docs. We split Trivy into a dedicated logical source so the
    customer's "exclude Trivy from dev/exec/platform numbers and surface them
    only on /admin" requirement can be enforced at the scope layer.
    """
    f = _map(_issue(rule="external_trivy:CVE-2021-44228"))
    assert f.source == SONARCLOUD_TRIVY_SOURCE


def test_external_trivy_rule_is_case_insensitive() -> None:
    """Defensive: SonarCloud doesn't strictly normalise case on the engineId
    portion. Match `EXTERNAL_TRIVY:` and `External_Trivy:` the same as the
    documented lower-case form so a caller-side casing change can't quietly
    re-leak Trivy rows into the dev/exec/platform views."""
    f = _map(_issue(rule="External_Trivy:CVE-2021-44228"))
    assert f.source == SONARCLOUD_TRIVY_SOURCE


def test_external_trivy_engine_variants_are_routed_to_trivy_source() -> None:
    """The org's importer can pick any `engineId` for Trivy — we've seen
    `external_trivy_scan:`, `external_aquasec_trivy:`, etc. The mapper
    matches any `external_<engine>:` whose engine portion contains `trivy`
    or `aqua` so a non-canonical engineId can't bypass the split."""
    f1 = _map(_issue(rule="external_trivy_scan:CVE-2026-12345"))
    f2 = _map(_issue(rule="external_aquasec_trivy:CVE-2026-67890"))
    f3 = _map(_issue(rule="external_aqua:CVE-2026-99999"))
    assert f1.source == SONARCLOUD_TRIVY_SOURCE
    assert f2.source == SONARCLOUD_TRIVY_SOURCE
    assert f3.source == SONARCLOUD_TRIVY_SOURCE


def test_avd_aquasec_url_in_message_is_routed_to_trivy_source() -> None:
    """The fallback signal: every Trivy CVE finding embeds a link to Aqua
    Security's vuln database (`https://avd.aquasec.com/nvd/cve-…`) in its
    message. Pinning that the URL signature alone is enough — this is the
    signal that caught ExampleOrg's exampleorg-org Trivy backlog when the rule
    prefix didn't match (the importer used a non-standard engineId)."""
    f = _map(
        _issue(
            rule="some-arbitrary-rule",
            message=(
                "Package: stdlib Installed Version: v1.26.1 Vulnerability "
                "CVE-2026-33811 Severity: HIGH Fixed Version: 1.25.10, 1.26.3 "
                "Link: [CVE-2026-33811](https://avd.aquasec.com/nvd/"
                "cve-2026-33811) - usr/libexec/ar-token: stdlib@v1.26.1"
            ),
        )
    )
    assert f.source == SONARCLOUD_TRIVY_SOURCE


def test_avd_aquasec_url_match_is_case_insensitive() -> None:
    """Defensive: Sonar might case-fold the URL when it stores the message.
    Pin that we don't depend on lowercase."""
    f = _map(_issue(rule=None, message="See https://AVD.aquasec.com/NVD/cve-2026-1"))
    assert f.source == SONARCLOUD_TRIVY_SOURCE


def test_native_sonar_rule_keeps_sonarcloud_source() -> None:
    """A regular Sonar rule (`java:S2076`, `python:S930`, …) still lands on
    the `sonarcloud` source and remains visible across every view. Pinning
    so the Trivy split doesn't accidentally swallow native Sonar findings."""
    f = _map(_issue(rule="java:S2076"))
    assert f.source == SONARCLOUD_SOURCE


def test_other_external_engine_keeps_sonarcloud_source() -> None:
    """Today only Trivy is split out per the customer ask. Other external
    engines (eslint, pmd, …) still land as plain `sonarcloud`. If/when a
    similar requirement appears for another engine, expand the rule-prefix
    table — don't change this default."""
    f = _map(_issue(rule="external_eslint:no-eval"))
    assert f.source == SONARCLOUD_SOURCE


def test_no_rule_keeps_sonarcloud_source() -> None:
    """A SonarCloud issue without a `rule` field is rare but possible (e.g.
    older snapshots); treat it as native Sonar rather than crashing or
    silently rerouting."""
    f = _map(_issue(rule=None))
    assert f.source == SONARCLOUD_SOURCE


def test_sonarcloud_finding_id_is_source_stable_across_classification() -> None:
    """`Finding.id` for SonarCloud findings is derived from the
    `sonarcloud:{native_id}` namespace regardless of whether the row ends up
    classified as `sonarcloud` or `sonarcloud_trivy`. This is *deliberate* —
    when the mapper's Trivy detection improves on a future deploy, an
    existing `source = "sonarcloud"` row that's now identifiable as Trivy
    must be re-stampable in place rather than auto-closing it and inserting
    a fresh row with a different id (which would leak the old row into
    /developer for N polls until auto-close).

    The classification lives in `Finding.source`, which the processor
    re-stamps from the incoming mapping — see
    `test_sonar_poll_reclassifies_existing_sonar_row_to_trivy_in_place`.
    """
    sonar = _map(_issue(key="SAME-KEY", rule="java:S2076"))
    trivy = _map(_issue(key="SAME-KEY", rule="external_trivy:CVE-2021-44228"))
    assert sonar.source == SONARCLOUD_SOURCE
    assert trivy.source == SONARCLOUD_TRIVY_SOURCE
    assert sonar.id == trivy.id


def test_map_snapshot_handles_empty(monkeypatch) -> None:
    from app.normalizer.mappers import sonarcloud as mod

    class _FakeCache:
        def get_ownership(self):
            class _O:
                sonar_key_to_asset_id: dict = {}

            return _O()

    monkeypatch.setattr(mod, "get_config_cache", lambda: _FakeCache())
    assert mod.map_snapshot({"organization": "exampleorg", "issues": []}) == []
    assert mod.map_snapshot({}) == []
