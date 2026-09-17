"""SonarCloud snapshot -> NormalizedFinding mapping.

Pinned to the SonarCloud REST shape:
    GET {SONAR_BASE_URL}/api/issues/search
        ?organization={org}
        &types=VULNERABILITY
        &statuses=OPEN,CONFIRMED,REOPENED
        &ps=500&p=N

Native ID:
    `sonarcloud:{organization}/{project_key}#{issue_key}`

`issue.key` is SonarCloud's persistent UUID — stable across rescans, so the derived
finding ID stays the same as long as Sonar doesn't garbage-collect the issue.

Severity mapping (table from ):
    BLOCKER  -> critical
    CRITICAL -> high       (Sonar's "critical" is conservative; calling it our
                            "critical" would inflate the headline KPI)
    MAJOR    -> medium
    MINOR    -> low
    INFO     -> info

Hotspots are intentionally NOT ingested in v1 — §"Alternatives considered".

Asset resolution: the mapper accepts an explicit sonar-key -> asset-id override
map (sourced from ownership.yaml's `sonar_project_key` fields) and falls back
to a `{org_lower}_{repo}` -> `{org}/{repo}` convention. Anything unmapped lands
as `repo:{project_key}` and gets stamped `unowned` by the processor. Two
asset_id prefixes are honoured:

    repo:<owner>/<name>       — a real GitHub repo asset
    sonarproj:<project_key>   — a synthetic Sonar-project asset (used when a
                                single GitHub repo hosts multiple Sonar projects
                                with distinct ownership, e.g. the `retail-api`
                                monorepo's three Retail API services in the
                                `exampledivision` org §"Multi-organisation").

The `sonarproj:` form has no 1:1 GitHub repo; the asset_display is the project
key itself so the dev-view component map can render the service label directly
("ExampleOrg.Commerce.Orders.API" -> "Orders API"). Both prefixes route through `team_for_asset`
the same way (the asset_id is just a stable string).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from app.core.config import get_settings
from app.core.config_store import get_config_cache
from app.core.enums import Severity
from app.normalizer.types import NormalizedFinding

SONARCLOUD_SOURCE = "sonarcloud"

# A separate logical source for SonarCloud-hosted issues that originated in an
# external scanner (today: Trivy). SonarCloud lets teams import third-party
# scanner reports as "external issues"; these surface on the same `/api/issues/search`
# response as native Sonar rule violations and would otherwise be indistinguishable
# from them in the dashboard. We split the source so:
#   - dev / executive / platform views never show or count them (per request);
#   - admins still see them via a dedicated `/admin` section ("Trivy issues in
#     SonarCloud") so the data isn't lost.
# The lifecycle (auto-close, reopen) still piggy-backs on the SonarCloud poller,
# which is why the snapshot processor expands `sonarcloud` -> {sonarcloud,
# sonarcloud_trivy} when computing absent / auto-close (see SOURCE_GROUPS in
# `app/normalizer/processor.py`).
SONARCLOUD_TRIVY_SOURCE = "sonarcloud_trivy"

# Trivy detection signals. Two layers, evaluated in order:
#
# 1. The `rule` field on a SonarCloud issue. SonarCloud's documented external-
#    issue format namespaces rules as `external_<engineId>:<ruleId>`
#    (docs.sonarsource.com/.../importing-external-issues/generic-issue-data).
#    The standard convention when importing Trivy is `engineId="trivy"` →
#    rule prefix `external_trivy:`. In practice the engineId is operator-
#    chosen, so we widen the match to any `external_*` whose engine portion
#    contains `trivy` or `aqua` — covers `external_trivy:`,
#    `external_trivy_scan:`, `external_aquasec_trivy:`, etc.
#
# 2. The `avd.aquasec.com` URL signature in the issue's `message` field.
#    Trivy hard-codes a link to Aqua Security's vulnerability database
#    (`https://avd.aquasec.com/nvd/...`) in every CVE finding — that domain
#    is canonical Trivy output, independent of how the importer was wired
#    up. This is the fallback that catches every Trivy entry regardless of
#    the engineId the importer chose, and it's how ExampleOrg's `exampleorg` org
#    surfaced its Trivy backlog (the import didn't use `engineId="trivy"`,
#    so signal #1 alone missed every row).
#
# A future "ALL external issues are admin-only" stance is a one-line edit to
# `_source_for_issue`; we deliberately keep Trivy-specific to match the
# customer ask ("exclude Trivy from dev/exec/platform numbers") instead of
# silently broadening the rule.
_EXTERNAL_RULE_PREFIX = "external_"
_TRIVY_ENGINE_TOKENS: tuple[str, ...] = ("trivy", "aqua")
_TRIVY_MESSAGE_FINGERPRINT = "avd.aquasec.com"

__all__ = [
    "SONARCLOUD_SOURCE",
    "SONARCLOUD_TRIVY_SOURCE",
    "NormalizedFinding",
    "map_issue",
    "map_snapshot",
    "native_id_for_issue",
]


_SEVERITY_MAP: dict[str, Severity] = {
    "BLOCKER": Severity.critical,
    "CRITICAL": Severity.high,
    "MAJOR": Severity.medium,
    "MINOR": Severity.low,
    "INFO": Severity.info,
}


def _parse_iso8601(value: str | None) -> datetime | None:
    """Sonar returns timestamps like `2025-09-01T12:34:56+0000`. `fromisoformat` on
    3.13 accepts both `+0000` and `+00:00`. Defensive: any failure returns None
    rather than crashing the mapper.
    """
    if not value:
        return None
    # Sonar uses `+0000` (no colon); 3.11+ `fromisoformat` accepts that, but normalise
    # for safety so older patch releases work too.
    candidate = value
    if len(candidate) >= 5 and candidate[-5] in "+-" and candidate[-3] != ":":
        candidate = candidate[:-2] + ":" + candidate[-2:]
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def _finding_id(source: str, native_id: str) -> UUID:
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"{source}:{native_id}")


def _sonarcloud_finding_id(native_id: str) -> UUID:
    """Source-stable Finding.id for SonarCloud-poller findings.

    Both `sonarcloud` and `sonarcloud_trivy` derive their id from the same
    `sonarcloud:{native_id}` namespace. Two reasons:

    1. **Reclassification migration.** When the mapper's Trivy-detection
       logic improves (signal added, signal corrected) and an existing row
       previously stored as `source = "sonarcloud"` is now identifiable as
       Trivy, the next poll's mapper output must match the existing row by
       id so the processor can re-stamp `source` in place. If the id varied
       per source, the existing row would be orphaned (auto-closed after N
       missed polls) while a brand-new `sonarcloud_trivy` row was inserted —
       the user-visible result is "I deployed the fix but Trivy entries
       still appear in /developer for hours". Source-stable id avoids that.

    2. **Identity contract.** The `(source, native_id)` pair is
       the identity contract; the `Finding.id` is derived from it. By
       choosing `sonarcloud` (the poller-level identity) as the namespace,
       we keep the contract honest at the poller level — the per-snapshot
       dedupe, the existing `uq_findings_source_native_id` constraint, and
       the absent-detection logic all still hold. The classification
       (sonarcloud vs sonarcloud_trivy) is a property of `Finding.source`,
       which the processor mutates as the mapper's view evolves.
    """
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"{SONARCLOUD_SOURCE}:{native_id}")


def _correlation_group_id(cve_id: str | None, asset_root: str) -> UUID | None:
    if not cve_id:
        return None
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"correlation:{cve_id}:{asset_root}")


def native_id_for_issue(organization: str, issue: dict[str, Any]) -> str:
    """`sonarcloud:{organization}/{project_key}#{issue_key}`."""
    project_key = issue["project"]
    issue_key = issue["key"]
    return f"{organization}/{project_key}#{issue_key}"


_ASSET_ID_PREFIXES = ("repo:", "sonarproj:")


def _strip_asset_prefix(asset_id: str) -> str:
    """Drop the asset-id namespace prefix for display.

    `repo:ExampleOrg/product-core` -> `ExampleOrg/product-core`.
    `sonarproj:ExampleOrg.Commerce.Orders.API` -> `ExampleOrg.Commerce.Orders.API`.
    Anything without a known prefix passes through unchanged.
    """
    for prefix in _ASSET_ID_PREFIXES:
        if asset_id.startswith(prefix):
            return asset_id[len(prefix) :]
    return asset_id


def _resolve_asset_id(
    project_key: str,
    organization: str,
    *,
    sonar_key_to_asset_id: dict[str, str],
) -> tuple[str, str, str]:
    """Return `(asset_id, asset_display, github_owner_repo_or_project_key)`.

    Resolution precedence:
      1. Explicit override: `ownership.yaml.assets[*].sonar_project_key` -> asset_id.
         Supports both `repo:<owner>/<name>` and `sonarproj:<key>` namespaces; the
         display value strips whichever prefix was used. The multi-org Retail API
         split uses `sonarproj:` because a single GitHub repo (retail-api) hosts
         three Sonar projects with three distinct owning teams — there's no real
         per-service repo to point at.
      2. Convention: `{org_lower}_{repo}` -> `repo:{settings.github_org}/{repo}`,
         only when `settings.github_org` is set. Repo names may contain
         underscores; only the first underscore after the org prefix is the
         separator.
      3. Fallback: `repo:{project_key}` (lands as `unowned`, intentionally so).
         Also taken when the convention path would apply but `GITHUB_ORG` is
         empty — see below.

    Why the convention path requires `settings.github_org`: SonarCloud
    organisation keys are always lowercase (Sonar enforces it; `exampleorg`),
    while GitHub preserves whatever casing the org was created with
    (`ExampleOrg`). `OwnershipMap.asset_to_team` is keyed off the GitHub
    canonical form, so synthesising `repo:{organization}/{repo}` from the
    lowercase Sonar org silently produces an asset_id that can't match
    `ownership.yaml.assets[*].id` exactly — those rows then read back as
    `unowned`, and the nightly rollup `core_reresolve` flips them back to
    `unowned` on every pass (the see-saw the cloud was exhibiting for
    `example-service` under Product). `OwnershipMap.team_for_asset` softens this at
    runtime via a case-insensitive `repo:` fallback, but the canonical fix
    is to require operators to configure `GITHUB_ORG` and otherwise fall
    through to the project-key escape valve so the misconfiguration shows
    up clearly on `/admin` (with a non-`org/repo`-shaped asset_id) instead
    of pretending to be canonical. The `validate-config` gate fails closed
    on cloud deploys when `GITHUB_ORG` is empty so this fallthrough is
    only reachable in dev/test.
    """
    if project_key in sonar_key_to_asset_id:
        asset_id = sonar_key_to_asset_id[project_key]
        display = _strip_asset_prefix(asset_id)
        return asset_id, display, display

    org_prefix_lower = organization.lower() + "_"
    if project_key.lower().startswith(org_prefix_lower):
        repo_name = project_key[len(org_prefix_lower) :]
        if repo_name:
            github_org = get_settings().github_org
            if github_org:
                full = f"{github_org}/{repo_name}"
                return f"repo:{full}", full, full
            # GITHUB_ORG unset: fall through to the project-key form rather
            # than silently producing a lowercase `repo:{organization}/...`.
            # Lands `unowned` on /admin until the operator either sets
            # GITHUB_ORG or adds a `sonar_project_key` override.

    return f"repo:{project_key}", project_key, project_key


def _is_trivy_issue(issue: dict[str, Any]) -> bool:
    """Multi-signal Trivy detection on a raw SonarCloud issue.

    Signal A (preferred): `rule` is an `external_<engineId>:<ruleId>` whose
    engine portion mentions `trivy` or `aqua`. This catches the canonical
    `external_trivy:CVE-…` rule plus the variants the org's importer
    actually uses (`external_trivy_scan:`, `external_aquasec_trivy:`, …).
    Engine matching is case-insensitive — Sonar's docs lower-case the
    engineId but the importer is operator-controlled and we refuse to depend
    on case normalisation we don't own.

    Signal B (fallback): the issue's `message` carries an `avd.aquasec.com`
    link. Trivy hard-codes a deep-link to Aqua Security's vulnerability
    database in every CVE finding ("Link: [CVE-…](https://avd.aquasec.com/
    nvd/cve-…)"); that URL is operator-independent. This caught ExampleOrg's
    exampleorg-org Trivy backlog when signal A alone returned zero — the
    importer there used a non-standard engineId, so the rule prefix didn't
    match, but every message still embedded the Aqua URL.

    Either signal is sufficient. Both are required to be cheap (string
    comparisons, no regex back-tracking) because this runs once per issue
    on every Sonar snapshot, ~1k issues per poll today.
    """
    rule = (issue.get("rule") or "").lower()
    if rule.startswith(_EXTERNAL_RULE_PREFIX):
        engine_part = rule[len(_EXTERNAL_RULE_PREFIX) :].split(":", 1)[0]
        if any(token in engine_part for token in _TRIVY_ENGINE_TOKENS):
            return True

    message = (issue.get("message") or "").lower()
    return _TRIVY_MESSAGE_FINGERPRINT in message


def _source_for_issue(issue: dict[str, Any]) -> str:
    """Return the logical `Finding.source` for a SonarCloud issue.

    Routes Trivy-imported entries to `sonarcloud_trivy` (admin-only); every
    other issue keeps the plain `sonarcloud` source. Other external engines
    (eslint, pmd, …) still land as plain `sonarcloud` until a similar
    customer requirement appears for them — for the rationale.
    """
    return SONARCLOUD_TRIVY_SOURCE if _is_trivy_issue(issue) else SONARCLOUD_SOURCE


def map_issue(
    issue: dict[str, Any],
    *,
    organization: str,
    sonar_key_to_asset_id: dict[str, str],
) -> NormalizedFinding:
    project_key = issue["project"]

    raw_severity = (issue.get("severity") or "INFO").upper()
    severity = _SEVERITY_MAP.get(raw_severity, Severity.info)

    # Sonar surfaces CWE/OWASP via `tags` like ["cwe:cwe-79", "owasp-a3"]. Pull the
    # first CWE we see; everything else stays in `tags` for later inspection.
    raw_tags: list[str] = issue.get("tags") or []
    cwe_id: str | None = None
    for tag in raw_tags:
        low = tag.lower()
        if low.startswith("cwe:") or low.startswith("cwe-"):
            payload = tag.split(":", 1)[1] if ":" in tag else tag
            cwe_id = payload.upper().replace("CWE-CWE-", "CWE-")
            if not cwe_id.startswith("CWE-"):
                cwe_id = f"CWE-{cwe_id}"
            break

    asset_id, asset_display, _ = _resolve_asset_id(
        project_key, organization, sonar_key_to_asset_id=sonar_key_to_asset_id
    )

    native_id = native_id_for_issue(organization, issue)
    rule = issue.get("rule")
    source = _source_for_issue(issue)
    title = (issue.get("message") or "").strip() or f"SonarCloud issue {issue.get('key')}"
    description = (issue.get("message") or "").strip()
    if rule:
        description = f"{description}\n\nrule: {rule}".strip()

    file_path = issue.get("component") or ""
    location_tag = (
        f"file:{file_path.split(':', 1)[1]}" if ":" in file_path else f"file:{file_path}"
    )
    tags_out = [f"rule:{rule}"] if rule else []
    if location_tag and location_tag != "file:":
        tags_out.append(location_tag)

    # asset_type tracks the asset_id namespace so downstream consumers can tell a
    # real GitHub repo from a synthetic Sonar-project asset (the Retail API
    # services in `exampledivision` are the only `sonarcloud_project` assets today).
    asset_type = (
        "sonarcloud_project" if asset_id.startswith("sonarproj:") else "github_repo"
    )

    # The id is derived from the *poller-level* source (`sonarcloud`), not
    # the per-row classified source. That keeps the id stable across
    # reclassification — when the mapper learns to recognise an existing
    # `sonarcloud` finding as Trivy on a future poll, the id matches and
    # the processor can re-stamp `Finding.source` in place rather than
    # auto-closing the old row + inserting a fresh one. See
    # `_sonarcloud_finding_id` for the full rationale.
    return NormalizedFinding(
        id=_sonarcloud_finding_id(native_id),
        source=source,
        native_id=native_id,
        title=title,
        description=description,
        severity=severity,
        cve_id=None,  # Sonar issues are rule-based; CVE attribution is rare and unreliable
        cwe_id=cwe_id,
        asset_id=asset_id,
        asset_type=asset_type,
        asset_root=asset_id,
        asset_display=asset_display,
        correlation_group_id=_correlation_group_id(None, asset_id),
        tags=tags_out,
        upstream_created_at=_parse_iso8601(issue.get("creationDate")),
    )


def map_snapshot(payload: dict[str, Any]) -> list[NormalizedFinding]:
    """Map the full SonarCloud snapshot envelope.

    The poller wraps each poll into one of two shapes:

    Single-org (legacy):
        {"organization": "<sonar-org>", "issues": [<issue>, ...]}

    Multi-org combined (current, avoids cross-org absent-marking):
        {"organization": "", "issues": [{"__org__": "<sonar-org>", ...issue...}, ...]}

    When `__org__` is present on an issue it takes precedence over the envelope-level
    `organization`. This allows the processor to see all orgs' findings in a single
    snapshot, eliminating the race condition where one org's snapshot marks the other
    org's findings absent and triggers mass auto-close.
    """
    envelope_org = payload.get("organization") or ""
    issues = payload.get("issues") or []

    # Sourced once per snapshot so we don't hit the cache 1000x.
    sonar_key_to_asset_id = get_config_cache().get_ownership().sonar_key_to_asset_id

    return [
        map_issue(
            i,
            organization=i.get("__org__") or envelope_org,
            sonar_key_to_asset_id=sonar_key_to_asset_id,
        )
        for i in issues
    ]
