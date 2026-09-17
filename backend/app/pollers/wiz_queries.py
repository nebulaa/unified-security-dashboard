"""GraphQL query templates for the Wiz poller.

Field selection matches the Wiz GraphQL schema (2026-05). Tenant API URL via
`WIZ_API_URL`. Some envelope keys (`sensitive_data`, `container`) are not
exposed on all tenants — the poller emits empty lists for those keys.

Scheduled polls ingest three detectors only:
issues, vulnerability_findings, cloud_config. Secrets and code remain available
via `--only-detector` for local debugging but are not scheduled.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

_APPLICATION_SERVICES = """
      applicationServices {
        id
        displayName
      }
"""

_ISSUE_NODE = f"""
        id
        status
        severity
        createdAt
        entitySnapshot {{
          id
          name
          type
          subscriptionId
          subscriptionExternalId
          subscriptionName
          cloudPlatform
        }}
        sourceRules {{
          name
          description
        }}
        {_APPLICATION_SERVICES}
"""

_VULN_NODE = f"""
        id
        status
        vendorSeverity
        name
        portalUrl
        CVEDescription
        description
        detailedName
        vulnerabilityExternalId
        firstDetectedAt
        hasCisaKevExploit
        vulnerableAsset {{
          ... on VulnerableAssetVirtualMachine {{
            id
            name
            cloudPlatform
            subscriptionExternalId
            subscriptionId
          }}
          ... on VulnerableAssetContainerImage {{
            id
            name
            cloudPlatform
            subscriptionExternalId
          }}
          ... on VulnerableAssetRepositoryBranch {{
            id
            name
          }}
          ... on VulnerableAssetServerless {{
            id
            name
            cloudPlatform
            subscriptionExternalId
          }}
        }}
        {_APPLICATION_SERVICES}
"""

_CONFIG_NODE = """
        id
        status
        severity
        firstSeenAt
        rule {
          name
          description
        }
        resource {
          id
          name
          cloudPlatform
          region
          subscription {
            id
            externalId
            cloudProvider
          }
        }
"""

_SECRET_NODE = f"""
        id
        status
        severity
        name
        path
        firstSeenAt
        {_APPLICATION_SERVICES}
"""

_IAC_NODE = """
        id
        severity
        status
        name
        firstSeenAt
"""


@dataclass(frozen=True)
class DetectorSpec:
    """One Wiz detector query executed sequentially by the poller."""

    name: str
    envelope_key: str
    graphql_root: str
    query: str
    build_filter: Callable[[bool, str | None], dict]


def _iac_filter(*, backfill: bool, backfill_after: str | None) -> dict:
    """IaC/code findings — CRITICAL+HIGH via nested `equals`."""
    filt: dict = {
        "severity": {"equals": ["CRITICAL", "HIGH"]},
    }
    # IaCFindingFilters exposes `createdAt`, not `firstSeenAt` (node still has firstSeenAt).
    if backfill and backfill_after:
        filt["createdAt"] = {"after": backfill_after}
    return filt


def _open_severity_filter(*, backfill: bool, backfill_after: str | None) -> dict:
    filt: dict = {
        "status": ["OPEN", "IN_PROGRESS"],
        "severity": ["CRITICAL", "HIGH"],
    }
    if backfill and backfill_after:
        filt["createdAt"] = {"after": backfill_after}
    return filt


def _vuln_filter(*, backfill: bool, backfill_after: str | None) -> dict:
    filt: dict = {
        "status": ["OPEN", "IN_PROGRESS"],
        "vendorSeverity": ["CRITICAL", "HIGH"],
        "hasCisaKevExploit": True,
        "hasExploit": True,
    }
    # VulnerabilityFindingFilters exposes `firstSeenAt`, not `firstDetectedAt`.
    if backfill and backfill_after:
        filt["firstSeenAt"] = {"after": backfill_after}
    return filt


def _config_filter(*, backfill: bool, backfill_after: str | None) -> dict:
    filt: dict = {
        "status": ["OPEN", "IN_PROGRESS"],
        "severity": ["CRITICAL", "HIGH"],
    }
    if backfill and backfill_after:
        filt["firstSeenAt"] = {"after": backfill_after}
    return filt


def _secret_filter(*, backfill: bool, backfill_after: str | None) -> dict:
    filt: dict = {
        "status": {"equals": ["OPEN"]},
        "severity": {"equals": ["CRITICAL", "HIGH"]},
    }
    if backfill and backfill_after:
        filt["firstSeenAt"] = {"after": backfill_after}
    return filt


SCHEDULED_DETECTORS: tuple[DetectorSpec, ...] = (
    DetectorSpec(
        name="issues",
        envelope_key="issues",
        graphql_root="issues",
        query=f"""
query WizIssues($filterBy: IssueFilters, $first: Int, $after: String) {{
  issues(filterBy: $filterBy, first: $first, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_ISSUE_NODE} }}
  }}
}}
""",
        build_filter=_open_severity_filter,
    ),
    DetectorSpec(
        name="vulnerability_findings",
        envelope_key="vulnerability_findings",
        graphql_root="vulnerabilityFindings",
        query=f"""
query WizVulnFindings($filterBy: VulnerabilityFindingFilters, $first: Int, $after: String) {{
  vulnerabilityFindings(filterBy: $filterBy, first: $first, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_VULN_NODE} }}
  }}
}}
""",
        build_filter=_vuln_filter,
    ),
    DetectorSpec(
        name="cloud_config",
        envelope_key="cloud_config",
        graphql_root="configurationFindings",
        query=f"""
query WizConfigFindings($filterBy: ConfigurationFindingFilters, $first: Int, $after: String) {{
  configurationFindings(filterBy: $filterBy, first: $first, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_CONFIG_NODE} }}
  }}
}}
""",
        build_filter=_config_filter,
    ),
)

# Removed from scheduled poll — `--only-detector` debugging only.
DEPRECATED_DETECTORS: tuple[DetectorSpec, ...] = (
    DetectorSpec(
        name="secrets",
        envelope_key="secrets",
        graphql_root="secretInstances",
        query=f"""
query WizSecretInstances($filterBy: SecretInstanceFilters, $first: Int, $after: String) {{
  secretInstances(filterBy: $filterBy, first: $first, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_SECRET_NODE} }}
  }}
}}
""",
        build_filter=_secret_filter,
    ),
    DetectorSpec(
        name="code",
        envelope_key="code",
        graphql_root="iacFindings",
        query=f"""
query WizIacFindings($filterBy: IaCFindingFilters, $first: Int, $after: String) {{
  iacFindings(filterBy: $filterBy, first: $first, after: $after) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{ {_IAC_NODE} }}
  }}
}}
""",
        build_filter=_iac_filter,
    ),
)

DETECTORS: tuple[DetectorSpec, ...] = SCHEDULED_DETECTORS + DEPRECATED_DETECTORS

# Envelope keys with no GraphQL root on this tenant/schema generation.
STUB_ENVELOPE_KEYS: tuple[str, ...] = ("sensitive_data", "container")

DETECTOR_BY_NAME: dict[str, DetectorSpec] = {d.name: d for d in DETECTORS}
