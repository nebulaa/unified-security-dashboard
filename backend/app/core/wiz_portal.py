"""Wiz portal deep links for dashboard rows (plans/wiz_platform_tab.plan.md)."""

from __future__ import annotations

import os

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

DEFAULT_WIZ_PORTAL_BASE = "https://app.wiz.io"

# Platform Wiz tab order.
WIZ_CATEGORY_ORDER: tuple[str, ...] = (
    "threat_center",
    "issue",
    "cloud_config",
    "vulnerability",
    "secret",
    "sensitive_data",
    "container",
    "code",
)

WIZ_CATEGORY_LABELS: dict[str, str] = {
    "threat_center": "Threat Center (30d)",
    "issue": "Wiz issues",
    "vulnerability": "CISA KEV CVEs",
    "cloud_config": "Cloud misconfigs",
    "secret": "Secrets",
    "sensitive_data": "Sensitive data",
    "container": "Container",
    "code": "Code",
}


def wiz_portal_base_url() -> str:
    """Wiz UI host — always app.wiz.io for ExampleOrg; not the regional GraphQL host."""
    explicit = os.environ.get("WIZ_PORTAL_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    try:
        from app.core.config import get_settings

        configured = get_settings().wiz_portal_base_url.strip().rstrip("/")
        if configured:
            return configured
    except Exception:
        pass
    return DEFAULT_WIZ_PORTAL_BASE


def wiz_finding_uuid(native_id: str) -> str | None:
    if not native_id.startswith("wiz:"):
        return None
    uid = native_id.removeprefix("wiz:").strip()
    return uid or None


def wiz_threat_center_url(threat_id: str) -> str:
    tid = threat_id.strip()
    return f"{wiz_portal_base_url()}/boards/threat-center/{tid}"


def wiz_portal_url(native_id: str, wiz_category: str | None) -> str | None:
    """Best-effort portal URL when GraphQL did not return portalUrl."""
    if wiz_category == "threat_center" and native_id.startswith("wiz:threat:"):
        return wiz_threat_center_url(native_id.removeprefix("wiz:threat:"))
    uid = wiz_finding_uuid(native_id)
    if not uid or not wiz_category or wiz_category not in WIZ_CATEGORIES:
        return None
    base = wiz_portal_base_url()
    if wiz_category == "issue":
        # Documented Wiz SPA route (Port.io / Wiz Jira automation templates).
        return f"{base}/issues#~(issue~'{uid})"
    if wiz_category == "cloud_config":
        # ConfigurationFinding has no portalUrl; Elastic integration entity deep link.
        return (
            f"{base}/findings/configuration-findings/cloud"
            f"#~(entity~(~'{uid}*2cCONFIGURATION_FINDING))"
        )
    return None


def resolve_wiz_upstream_url(
    node: dict,
    *,
    native_id: str,
    wiz_category: str,
) -> str | None:
    """Prefer portalUrl from the Wiz GraphQL node; fall back to category hash URLs."""
    for key in ("portalUrl", "link"):
        raw = node.get(key)
        if isinstance(raw, str) and raw.startswith("https://"):
            return raw.strip()
    return wiz_portal_url(native_id, wiz_category)
