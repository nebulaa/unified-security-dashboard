"""Wiz cloud subscription → /platform pillar tab (config/wiz_subscription_pillar.yaml)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import Finding
from app.core.wiz_auto_map import strip_inline_comment

PLATFORM_PILLAR_TAG_PREFIX = "platform_pillar:"
THREAT_INTEL_PILLAR = "threat-intel"


def is_threat_intel_pillar(pillar: str) -> bool:
    return pillar == THREAT_INTEL_PILLAR


def is_product_platform_pillar(pillar: str) -> bool:
    return bool(pillar) and not is_threat_intel_pillar(pillar)


def platform_pillar_tag(pillar: str) -> str:
    return f"{PLATFORM_PILLAR_TAG_PREFIX}{pillar}"


def pillar_from_tags(tags: list[str] | tuple[str, ...]) -> str | None:
    for tag in tags:
        if tag.startswith(PLATFORM_PILLAR_TAG_PREFIX):
            return tag.removeprefix(PLATFORM_PILLAR_TAG_PREFIX)
    return None


def platform_code_team_for_pillar(pillar: str) -> str | None:
    """Resolve a pillar's platform team from the component registry."""
    if is_threat_intel_pillar(pillar):
        return None
    from app.core.config_store import get_config_cache

    teams = get_config_cache().get_component_registry().teams_for_executive_pillar(pillar)
    conventional = f"{pillar}-platform"
    if conventional in teams:
        return conventional
    candidates = [team for team in teams if "platform" in team.split("-")]
    return candidates[0] if len(candidates) == 1 else None


def owner_team_for_wiz_platform_tags(tags: list[str] | tuple[str, ...]) -> str | None:
    """Resolve owner_team for Wiz orphan cloud resources from `platform_pillar:*`."""
    pillar = pillar_from_tags(tags)
    if not pillar:
        return None
    return platform_code_team_for_pillar(pillar)


def _normalize_pillar(raw: object) -> str | None:
    if raw is None:
        return None
    text = strip_inline_comment(str(raw).strip())
    if not text or text.lower() in {"null", "none", ""}:
        return None
    return text.lower()


@dataclass(frozen=True)
class WizSubscriptionPillarMap:
    default_pillar: str | None = None
    by_external_id: dict[str, str] = field(default_factory=dict)
    by_name: dict[str, str] = field(default_factory=dict)
    name_patterns: tuple[tuple[str, str], ...] = ()
    loaded_at: float = 0.0

    def resolve(
        self,
        *,
        external_id: str | None = None,
        name: str | None = None,
    ) -> str | None:
        ext = str(external_id or "").strip()
        if ext and ext in self.by_external_id:
            return self.by_external_id[ext]

        names_to_try: list[str] = []
        if name:
            names_to_try.append(str(name).strip())
        if ext:
            names_to_try.append(ext)

        for candidate in names_to_try:
            key = candidate.lower()
            if key in self.by_name:
                return self.by_name[key]

        haystacks = [s.lower() for s in names_to_try if s]
        for pattern, pillar in self.name_patterns:
            pat = pattern.lower()
            if any(pat in h for h in haystacks):
                return pillar

        return self.default_pillar


def parse_wiz_subscription_pillar(text: str) -> WizSubscriptionPillarMap:
    raw = yaml.safe_load(text) or {}
    default_pillar = _normalize_pillar(raw.get("default_pillar"))

    by_external_id: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for item in raw.get("subscriptions") or []:
        if not isinstance(item, dict):
            continue
        pillar = _normalize_pillar(item.get("pillar"))
        if not pillar:
            continue
        ext = str(item.get("external_id") or "").strip()
        if ext:
            by_external_id[ext] = pillar
        sub_name = str(item.get("name") or "").strip()
        if sub_name:
            by_name[sub_name.lower()] = pillar

    patterns: list[tuple[str, str]] = []
    for item in raw.get("name_patterns") or []:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or "").strip()
        pillar = _normalize_pillar(item.get("pillar"))
        if pattern and pillar:
            patterns.append((pattern, pillar))

    return WizSubscriptionPillarMap(
        default_pillar=default_pillar,
        by_external_id=by_external_id,
        by_name=by_name,
        name_patterns=tuple(patterns),
        loaded_at=time.time(),
    )


def load_wiz_subscription_pillar_map(config_dir: Any) -> WizSubscriptionPillarMap:
    path = config_dir / "wiz_subscription_pillar.yaml"
    if not path.is_file():
        return WizSubscriptionPillarMap(loaded_at=time.time())
    return parse_wiz_subscription_pillar(path.read_text(encoding="utf-8"))


def subscription_fields_from_node(node: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extract subscription external id and display name from a Wiz GraphQL node."""
    resource = node.get("resource") or {}
    sub = resource.get("subscription") or {}
    vulnerable = node.get("vulnerableAsset") or {}
    entity = node.get("entitySnapshot") or {}

    external_id = (
        sub.get("externalId")
        or resource.get("providerId")
        or vulnerable.get("subscriptionExternalId")
        or entity.get("subscriptionExternalId")
    )
    name = (
        sub.get("name")
        or vulnerable.get("subscriptionName")
        or entity.get("subscriptionName")
    )
    ext = str(external_id).strip() if external_id else None
    nm = str(name).strip() if name else None
    return ext or None, nm or None


def apply_platform_pillar_tags(
    tags: list[str],
    *,
    pillar_map: WizSubscriptionPillarMap,
    external_id: str | None,
    name: str | None,
) -> list[str]:
    """Return tags with at most one `platform_pillar:*` tag from subscription mapping."""
    kept = [t for t in tags if not t.startswith(PLATFORM_PILLAR_TAG_PREFIX)]
    pillar = pillar_map.resolve(external_id=external_id, name=name)
    if pillar:
        kept.append(platform_pillar_tag(pillar))
    return kept


_CLOUD_ACCOUNT_PREFIX = "cloud_account:"
_SUBSCRIPTION_NAME_PREFIX = "subscription_name:"


def _subscription_from_tags(tags: list[str] | tuple[str, ...]) -> tuple[str | None, str | None]:
    external_id: str | None = None
    name: str | None = None
    for tag in tags:
        if tag.startswith(_CLOUD_ACCOUNT_PREFIX):
            external_id = tag.removeprefix(_CLOUD_ACCOUNT_PREFIX)
        elif tag.startswith(_SUBSCRIPTION_NAME_PREFIX):
            name = tag.removeprefix(_SUBSCRIPTION_NAME_PREFIX)
    return external_id, name


def reresolve_wiz_cloud_owner_teams(
    session: Session,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Re-stamp owner_team on open Wiz `cloudres:*` rows from `platform_pillar:*` tags."""
    from app.core.enums import Status
    from app.normalizer.processor import UNOWNED_TEAM

    open_statuses = [s.value for s in Status.open_set()]
    rows = session.scalars(
        select(Finding).where(
            Finding.source == "wiz",
            Finding.status.in_(open_statuses),
            Finding.asset_id.like("cloudres:%"),
        )
    ).all()
    scanned = len(rows)
    updated = 0
    for row in rows:
        new_team = owner_team_for_wiz_platform_tags(row.tags or []) or UNOWNED_TEAM
        if row.owner_team == new_team:
            continue
        if not dry_run:
            row.owner_team = new_team
        updated += 1
    if not dry_run and updated:
        session.commit()
    return scanned, updated


def reresolve_wiz_platform_pillar_tags(
    session: Session,
    pillar_map: WizSubscriptionPillarMap,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Re-stamp `platform_pillar:*` tags on open Wiz findings from `cloud_account:` tags."""
    from app.core.enums import Status

    open_statuses = [s.value for s in Status.open_set()]
    rows = session.scalars(
        select(Finding).where(
            Finding.source == "wiz",
            Finding.status.in_(open_statuses),
        )
    ).all()
    scanned = len(rows)
    updated = 0
    for row in rows:
        ext, name = _subscription_from_tags(row.tags or [])
        new_tags = apply_platform_pillar_tags(
            list(row.tags or []),
            pillar_map=pillar_map,
            external_id=ext,
            name=name,
        )
        if new_tags == list(row.tags or []):
            continue
        if not dry_run:
            row.tags = new_tags
        updated += 1
    if not dry_run and updated:
        session.commit()
    return scanned, updated


def validate_wiz_subscription_pillar_map(pillar_map: WizSubscriptionPillarMap) -> list[str]:
    errors: list[str] = []
    if not pillar_map.by_external_id and not pillar_map.by_name and not pillar_map.name_patterns:
        errors.append(
            "wiz_subscription_pillar.yaml: no subscriptions or name_patterns defined"
        )
    return errors
