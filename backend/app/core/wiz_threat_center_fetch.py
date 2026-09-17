"""Wiz Threat Center polling — impacted advisories in the last N days."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx


def _graphql_errors(data: dict[str, Any]) -> list[dict[str, Any]]:
    errors = data.get("errors")
    if isinstance(errors, list):
        return errors
    return []


_THREAT_CENTER_ITEMS = """
query WizThreatCenterItems($first: Int, $after: String) {
  threatCenterItems(first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      title
      description
      type
      source
      publishedAt
      updatedAt
      findingLinks { type filters message }
    }
  }
}
"""

_COUNT_QUERY = """
query WizThreatImpactCount($filterBy: {filter_type}, $first: Int) {{
  {root}(filterBy: $filterBy, first: $first) {{
    totalCount
  }}
}}
"""

_LINK_SPECS: dict[str, tuple[str, str]] = {
    "ISSUES": ("issues", "IssueFilters"),
    "VULNERABILITY_FINDINGS": ("vulnerabilityFindings", "VulnerabilityFindingFilters"),
    "CLOUD_CONFIGURATION_FINDINGS": ("configurationFindings", "ConfigurationFindingFilters"),
    "HOST_CONFIGURATION_FINDINGS": ("hostConfigurationFindings", "HostConfigurationFindingFilters"),
    "SECRET_FINDINGS": ("secretInstances", "SecretInstanceFilters"),
    "THREATS": ("detections", "DetectionFilters"),
}


@dataclass(frozen=True)
class ThreatCenterImpact:
    threat_id: str
    title: str
    description: str
    threat_type: str
    source: str | None
    published_at: str
    updated_at: str | None
    impact_total: int
    impact_breakdown: dict[str, int]


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalize_equals(value: Any) -> list[Any]:
    if isinstance(value, dict) and "equals" in value:
        eq = value["equals"]
        return eq if isinstance(eq, list) else [eq]
    if isinstance(value, list):
        return value
    return [value]


def _translate_common_filter(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if key in {"status", "severity", "vendorSeverity"}:
            eq = _normalize_equals(val)
            if eq:
                out[key if key != "vendorSeverity" else "vendorSeverity"] = eq
        elif key == "vulnerabilityExternalId":
            eq = _normalize_equals(val)
            if eq:
                out["vulnerabilityExternalIdV2"] = {"equals": eq}
        elif key in {"createdAt", "firstSeenAt", "updatedAt"}:
            out[key] = val
        elif key == "resource":
            out["resource"] = val
        elif key == "frameworkCategory":
            out["frameworkCategory"] = _normalize_equals(val)
    return out


def _translate_detection_filter(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "createdAt" in raw:
        out["createdAt"] = raw["createdAt"]
    if "sourceRule" in raw:
        rules = _normalize_equals(raw["sourceRule"])
        out["matchedRule"] = [{"id": str(rule)} for rule in rules if rule]
    if "status" in raw:
        eq = _normalize_equals(raw["status"])
        if eq:
            out["status"] = {"equals": eq}
    return out


def translate_threat_link_filter(link_type: str, raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not raw:
        return None
    if link_type == "THREATS":
        translated = _translate_detection_filter(raw)
    else:
        translated = _translate_common_filter(raw)
    return translated or None


def _count_with_filter(
    *,
    api_url: str,
    token: str,
    root: str,
    filter_type: str,
    filter_by: dict[str, Any],
    client: httpx.Client,
) -> int:
    query = _COUNT_QUERY.format(root=root, filter_type=filter_type)
    response = client.post(
        api_url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query, "variables": {"filterBy": filter_by, "first": 1}},
    )
    if response.status_code == 401:
        raise RuntimeError("wiz threat center: GraphQL 401 — token invalid or expired")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    errors = _graphql_errors(payload)
    if errors or response.status_code >= 400:
        messages = "; ".join(str(e.get("message", e)) for e in errors)
        if not messages:
            messages = response.text.strip() or f"HTTP {response.status_code}"
        raise RuntimeError(f"wiz threat center: GraphQL error on {root}: {messages}")
    connection = (payload.get("data") or {}).get(root) or {}
    total = connection.get("totalCount")
    return int(total or 0)


def count_threat_impact(
    *,
    api_url: str,
    token: str,
    threat_id: str,
    finding_links: list[dict[str, Any]],
    client: httpx.Client,
) -> tuple[int, dict[str, int]]:
    breakdown: dict[str, int] = {}
    total = 0

    advisory_count = _count_with_filter(
        api_url=api_url,
        token=token,
        root="detections",
        filter_type="DetectionFilters",
        filter_by={"advisory": {"equals": [threat_id]}},
        client=client,
    )
    if advisory_count:
        breakdown["ADVISORY_DETECTIONS"] = advisory_count
        total += advisory_count

    for link in finding_links:
        link_type = str(link.get("type") or "").strip()
        raw_filters = link.get("filters")
        if not link_type or not isinstance(raw_filters, dict):
            continue
        spec = _LINK_SPECS.get(link_type)
        if spec is None:
            continue
        translated = translate_threat_link_filter(link_type, raw_filters)
        if not translated:
            continue
        root, filter_type = spec
        try:
            count = _count_with_filter(
                api_url=api_url,
                token=token,
                root=root,
                filter_type=filter_type,
                filter_by=translated,
                client=client,
            )
        except RuntimeError:
            continue
        if count > 0:
            breakdown[link_type] = count
            total += count
    return total, breakdown


def poll_impacted_threat_center_items(
    *,
    api_url: str,
    token: str,
    days: int,
    client: httpx.Client,
) -> list[dict[str, Any]]:
    """Return Threat Center advisories published in the last `days` with env impact."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    nodes: list[dict[str, Any]] = []
    after: str | None = None

    while True:
        variables: dict[str, Any] = {"first": 100}
        if after:
            variables["after"] = after
        response = client.post(
            api_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": _THREAT_CENTER_ITEMS, "variables": variables},
        )
        if response.status_code == 401:
            raise RuntimeError("wiz threat center: GraphQL 401 — token invalid or expired")
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        errors = _graphql_errors(payload)
        if errors or response.status_code >= 400:
            messages = "; ".join(str(e.get("message", e)) for e in errors)
            if not messages:
                messages = response.text.strip() or f"HTTP {response.status_code}"
            raise RuntimeError(f"wiz threat center: GraphQL error: {messages}")

        connection = (payload.get("data") or {}).get("threatCenterItems") or {}
        page_nodes = connection.get("nodes") or []
        nodes.extend(page_nodes)
        page_info = connection.get("pageInfo") or {}
        if page_info.get("hasNextPage"):
            after = page_info.get("endCursor")
            if not after:
                break
        else:
            break

    impacted: list[dict[str, Any]] = []
    for node in nodes:
        published = _parse_iso8601(node.get("publishedAt"))
        if published is None or published < cutoff:
            continue
        threat_id = str(node.get("id") or "").strip()
        if not threat_id:
            continue
        links = node.get("findingLinks") or []
        if not isinstance(links, list):
            links = []
        impact_total, impact_breakdown = count_threat_impact(
            api_url=api_url,
            token=token,
            threat_id=threat_id,
            finding_links=links,
            client=client,
        )
        if impact_total <= 0:
            continue
        enriched = dict(node)
        enriched["impactTotal"] = impact_total
        enriched["impactBreakdown"] = impact_breakdown
        impacted.append(enriched)
    return impacted
