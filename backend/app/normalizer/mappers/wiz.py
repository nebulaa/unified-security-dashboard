"""Wiz combined snapshot -> NormalizedFinding."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from app.core.config import get_settings
from app.core.config_store import get_config_cache
from app.core.enums import Severity
from app.core.wiz_portal import resolve_wiz_upstream_url
from app.core.wiz_subscription_pillar import (
    THREAT_INTEL_PILLAR,
    apply_platform_pillar_tags,
    owner_team_for_wiz_platform_tags,
    platform_pillar_tag,
    subscription_fields_from_node,
)
from app.normalizer.types import NormalizedFinding

WIZ_SOURCE = "wiz"

WIZ_CATEGORIES = frozenset(
    {
        "issue",
        "vulnerability",
        "cloud_config",
        "secret",
        "sensitive_data",
        "container",
        "code",
        "threat_center",
    }
)

ENVELOPE_TO_CATEGORY: dict[str, str] = {
    "issues": "issue",
    "vulnerability_findings": "vulnerability",
    "cloud_config": "cloud_config",
    "secrets": "secret",
    "sensitive_data": "sensitive_data",
    "container": "container",
    "code": "code",
}

_SEVERITY_MAP: dict[str, Severity] = {
    "CRITICAL": Severity.critical,
    "HIGH": Severity.high,
    "critical": Severity.critical,
    "high": Severity.high,
}


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _finding_id(native_id: str) -> UUID:
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"{WIZ_SOURCE}:{native_id}")


def native_id_for_node(node: dict[str, Any]) -> str:
    wiz_id = node.get("id")
    if not wiz_id:
        raise ValueError("wiz node missing id")
    return f"wiz:{wiz_id}"


def _severity_for_node(node: dict[str, Any], category: str) -> Severity:
    raw = (
        node.get("severity")
        or node.get("vendorSeverity")
        or node.get("CVSSSeverity")
        or "HIGH"
    )
    key = str(raw).upper() if category != "vulnerability" else str(raw).upper()
    return _SEVERITY_MAP.get(key, Severity.high)


def _title_for_node(node: dict[str, Any], category: str) -> str:
    if node.get("name"):
        return str(node["name"]).strip()
    rule = node.get("rule") or {}
    if rule.get("name"):
        return str(rule["name"]).strip()
    source_rules = node.get("sourceRules") or []
    if source_rules and source_rules[0].get("name"):
        return str(source_rules[0]["name"]).strip()
    source_rule = node.get("sourceRule") or {}
    if source_rule.get("name"):
        return str(source_rule["name"]).strip()
    entity = node.get("entitySnapshot") or {}
    if entity.get("name"):
        return str(entity["name"]).strip()
    return f"Wiz {category} finding"


def _description_for_node(node: dict[str, Any]) -> str:
    for key in ("description", "CVEDescription", "controlDescription"):
        val = node.get(key)
        if val:
            return str(val).strip()
    rule = node.get("rule") or {}
    if rule.get("description"):
        return str(rule["description"]).strip()
    source_rules = node.get("sourceRules") or []
    if source_rules and source_rules[0].get("description"):
        return str(source_rules[0]["description"]).strip()
    source_rule = node.get("sourceRule") or {}
    if source_rule.get("controlDescription"):
        return str(source_rule["controlDescription"]).strip()
    return ""


def _upstream_created_at(node: dict[str, Any]) -> datetime | None:
    for key in ("firstSeenAt", "firstDetectedAt", "createdAt"):
        parsed = _parse_iso8601(node.get(key))
        if parsed:
            return parsed
    return None


def _cve_id(node: dict[str, Any], category: str) -> str | None:
    if category != "vulnerability":
        return None
    ext = node.get("vulnerabilityExternalId")
    if ext and str(ext).upper().startswith("CVE-"):
        return str(ext)
    name = str(node.get("name") or "")
    if name.upper().startswith("CVE-"):
        return name.split()[0]
    return None


def _tags_for_node(node: dict[str, Any], category: str) -> list[str]:
    tags = [f"wiz_category:{category}"]
    resource = node.get("resource") or {}
    sub = resource.get("subscription") or {}
    vulnerable = node.get("vulnerableAsset") or {}
    entity = node.get("entitySnapshot") or {}
    provider = (
        sub.get("cloudProvider")
        or resource.get("cloudProvider")
        or resource.get("cloudPlatform")
        or vulnerable.get("cloudPlatform")
        or entity.get("cloudPlatform")
    )
    if provider:
        tags.append(f"cloud_provider:{provider}")
    external_id, subscription_name = subscription_fields_from_node(node)
    if external_id:
        tags.append(f"cloud_account:{external_id}")
    if subscription_name:
        tags.append(f"subscription_name:{subscription_name}")
    if resource.get("region"):
        tags.append(f"region:{resource['region']}")
    if resource.get("type"):
        tags.append(f"resource_type:{resource['type']}")
    pillar_map = get_config_cache().get_wiz_subscription_pillar()
    return apply_platform_pillar_tags(
        tags,
        pillar_map=pillar_map,
        external_id=external_id,
        name=subscription_name,
    )


def _first_application_service_slug(node: dict[str, Any]) -> str | None:
    apps = node.get("applicationServices") or []
    if not apps:
        return None
    app = apps[0]
    # Wiz exposes displayName; registry `wiz_service:` should use the same slug/name.
    for key in ("displayName", "id"):
        val = app.get(key)
        if val:
            return str(val).strip()
    return None


def _cloud_asset_from_fields(
    *,
    provider: str | None,
    account: str | None,
    rid: str | None,
    display: str | None,
) -> tuple[str, str, str]:
    prov = str(provider or "unknown")
    acct = str(account or "unknown")
    resource_id = str(rid or "unknown")
    label = str(display or resource_id)
    return f"cloudres:{prov}/{acct}/{resource_id}", "cloud_resource", label


def _resolve_asset(
    node: dict[str, Any],
) -> tuple[str, str, str]:
    """Return asset_id, asset_type, asset_display."""
    service_slug = _first_application_service_slug(node)
    if service_slug:
        return f"wizservice:{service_slug}", "wiz_service", service_slug

    # Legacy shape (older query templates).
    service = node.get("service") or {}
    legacy_slug = service.get("slug") or service.get("name")
    if legacy_slug:
        slug_str = str(legacy_slug).strip()
        return f"wizservice:{slug_str}", "wiz_service", slug_str

    resource = node.get("resource") or {}
    entity = node.get("entitySnapshot") or {}
    vulnerable = node.get("vulnerableAsset") or {}

    if vulnerable:
        return _cloud_asset_from_fields(
            provider=vulnerable.get("cloudPlatform"),
            account=vulnerable.get("subscriptionExternalId")
            or vulnerable.get("subscriptionId"),
            rid=vulnerable.get("id") or vulnerable.get("name"),
            display=vulnerable.get("name"),
        )

    if not resource and entity:
        return _cloud_asset_from_fields(
            provider=entity.get("cloudPlatform"),
            account=entity.get("subscriptionExternalId") or entity.get("subscriptionId"),
            rid=entity.get("id") or entity.get("name"),
            display=entity.get("name"),
        )

    if resource:
        sub = resource.get("subscription") or {}
        return _cloud_asset_from_fields(
            provider=sub.get("cloudProvider") or resource.get("cloudPlatform"),
            account=sub.get("externalId") or resource.get("providerId"),
            rid=resource.get("id") or resource.get("providerId") or resource.get("name"),
            display=resource.get("name"),
        )

    return "wizservice:unknown", "wiz_service", "unknown"


def native_id_for_threat(node: dict[str, Any]) -> str:
    threat_id = node.get("id")
    if not threat_id:
        raise ValueError("wiz threat center node missing id")
    return f"wiz:threat:{threat_id}"


def _severity_for_threat(_node: dict[str, Any]) -> Severity:
    return Severity.high


def _tags_for_threat(node: dict[str, Any]) -> list[str]:
    tags = [
        "wiz_category:threat_center",
        f"threat_id:{node.get('id')}",
        platform_pillar_tag(THREAT_INTEL_PILLAR),
    ]
    impact = node.get("impactTotal")
    if impact is not None:
        tags.append(f"threat_impact:{impact}")
    return tags


def _description_for_threat(node: dict[str, Any]) -> str:
    base = str(node.get("description") or node.get("advisory") or "").strip()
    impact = int(node.get("impactTotal") or 0)
    breakdown = node.get("impactBreakdown") or {}
    parts = [base] if base else []
    if impact > 0:
        detail = ", ".join(f"{k}: {v}" for k, v in sorted(breakdown.items()))
        parts.append(f"Affected resources in your environment: {impact} ({detail}).")
    return "\n\n".join(parts).strip()


def map_threat_center_node(node: dict[str, Any]) -> NormalizedFinding:
    native_id = native_id_for_threat(node)
    title = str(node.get("title") or "Wiz Threat Center advisory").strip()
    return NormalizedFinding(
        id=_finding_id(native_id),
        source=WIZ_SOURCE,
        native_id=native_id,
        title=title,
        description=_description_for_threat(node),
        severity=_severity_for_threat(node),
        cve_id=None,
        cwe_id=None,
        asset_id="wizservice:threat-center",
        asset_type="wiz_service",
        asset_root="wizservice:threat-center",
        asset_display="Threat Center",
        correlation_group_id=None,
        tags=_tags_for_threat(node),
        upstream_created_at=_parse_iso8601(node.get("publishedAt")),
        wiz_category="threat_center",
        upstream_url=resolve_wiz_upstream_url(
            node, native_id=native_id, wiz_category="threat_center"
        ),
    )


def map_node(node: dict[str, Any], category: str) -> NormalizedFinding:
    native_id = native_id_for_node(node)
    asset_id, asset_type, asset_display = _resolve_asset(node)
    tags = _tags_for_node(node, category)
    owner_team = (
        owner_team_for_wiz_platform_tags(tags)
        if asset_type == "cloud_resource"
        else None
    )
    return NormalizedFinding(
        id=_finding_id(native_id),
        source=WIZ_SOURCE,
        native_id=native_id,
        title=_title_for_node(node, category),
        description=_description_for_node(node),
        severity=_severity_for_node(node, category),
        cve_id=_cve_id(node, category),
        cwe_id=None,
        asset_id=asset_id,
        asset_type=asset_type,
        asset_root=asset_id,
        asset_display=asset_display,
        correlation_group_id=None,
        tags=tags,
        upstream_created_at=_upstream_created_at(node),
        wiz_category=category,
        upstream_url=resolve_wiz_upstream_url(
            node, native_id=native_id, wiz_category=category
        ),
        owner_team=owner_team,
    )


def map_snapshot(envelope: dict[str, Any]) -> list[NormalizedFinding]:
    registry = get_config_cache().get_component_registry()
    # Registry load validates config is present; mapper uses asset_id only.
    _ = registry

    out: list[NormalizedFinding] = []
    for envelope_key, category in ENVELOPE_TO_CATEGORY.items():
        for node in envelope.get(envelope_key) or []:
            if not isinstance(node, dict):
                continue
            out.append(map_node(node, category))
    for node in envelope.get("threat_center") or []:
        if isinstance(node, dict):
            out.append(map_threat_center_node(node))
    return out
