"""Resolve `Finding.owner_team` from ownership.yaml, Wiz registry, and pillar tags."""

from __future__ import annotations

from app.core.config_store import OwnershipMap
from app.core.wiz_subscription_pillar import owner_team_for_wiz_platform_tags
from app.normalizer.processor import UNOWNED_TEAM


def resolve_finding_owner_team(
    *,
    source: str,
    asset_id: str,
    tags: list[str] | None,
    ownership: OwnershipMap,
    wiz_service_to_team: dict[str, str],
) -> str:
    """Authoritative owner_team for re-resolve and ingest fallback."""
    if source == "wiz":
        if asset_id.startswith("wizservice:"):
            slug = asset_id.removeprefix("wizservice:")
            return wiz_service_to_team.get(slug, UNOWNED_TEAM)
        if asset_id.startswith("cloudres:"):
            return owner_team_for_wiz_platform_tags(tags or []) or UNOWNED_TEAM
    return ownership.team_for_asset(asset_id)
