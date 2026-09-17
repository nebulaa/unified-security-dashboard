"""Dependabot snapshot -> NormalizedFinding mapping.

Pinned to the Dependabot REST shape:
    GET /orgs/{org}/dependabot/alerts?state=open

Native ID:
    `{owner}/{repo}#{alert_number}`

Only `state=open` alerts are pulled. Dismissed/fixed alerts disappear from the
snapshot, so the auto-close mechanism transitions them to `auto_closed` after the
threshold ( — the dashboard cannot tell upstream-fix from upstream-suppress,
so it doesn't pretend to).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from app.core.config import get_settings
from app.core.enums import Severity
from app.normalizer.types import NormalizedFinding

DEPENDABOT_SOURCE = "dependabot"

__all__ = ["DEPENDABOT_SOURCE", "NormalizedFinding", "map_alert", "map_snapshot", "native_id_for_alert"]


def _parse_iso8601(value: str | None) -> datetime | None:
    """GitHub returns RFC 3339 with a `Z` suffix; `fromisoformat` handles it on 3.11+."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.critical,
    "high": Severity.high,
    "medium": Severity.medium,
    "moderate": Severity.medium,
    "low": Severity.low,
}


def _finding_id(source: str, native_id: str) -> UUID:
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"{source}:{native_id}")


def _correlation_group_id(cve_id: str | None, asset_root: str) -> UUID | None:
    if not cve_id:
        return None
    namespace = UUID(get_settings().namespace_secdb)
    return uuid5(namespace, f"correlation:{cve_id}:{asset_root}")


def native_id_for_alert(alert: dict[str, Any]) -> str:
    """Pinned — `{owner}/{repo}#{alert_number}`."""
    full_name = alert["repository"]["full_name"]
    number = alert["number"]
    return f"{full_name}#{number}"


def map_alert(alert: dict[str, Any]) -> NormalizedFinding:
    full_name = alert["repository"]["full_name"]
    advisory = alert.get("security_advisory") or {}

    raw_severity = (advisory.get("severity") or "low").lower()
    severity = _SEVERITY_MAP.get(raw_severity, Severity.low)

    cve_id = advisory.get("cve_id")
    cwe_ids = advisory.get("cwe_ids") or []
    cwe_id = cwe_ids[0] if cwe_ids else None

    native_id = native_id_for_alert(alert)
    asset_id = f"repo:{full_name}"

    package = (alert.get("dependency") or {}).get("package") or {}
    package_label = package.get("name") or "unknown"

    title = (advisory.get("summary") or "").strip()
    if not title:
        title = f"Dependabot alert in {full_name} ({package_label})"

    description = (advisory.get("description") or "").strip()

    return NormalizedFinding(
        id=_finding_id(DEPENDABOT_SOURCE, native_id),
        source=DEPENDABOT_SOURCE,
        native_id=native_id,
        title=title,
        description=description,
        severity=severity,
        cve_id=cve_id,
        cwe_id=cwe_id,
        asset_id=asset_id,
        asset_type="github_repo",
        asset_root=asset_id,
        asset_display=full_name,
        correlation_group_id=_correlation_group_id(cve_id, asset_id),
        tags=[f"package:{package_label}"] if package_label else [],
        upstream_created_at=_parse_iso8601(alert.get("created_at")),
    )


def map_snapshot(payload: list[dict[str, Any]]) -> list[NormalizedFinding]:
    return [map_alert(a) for a in payload]
