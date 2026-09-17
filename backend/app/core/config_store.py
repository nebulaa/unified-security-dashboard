"""Config file loaders with in-memory cache and 10-minute refresh fallback.

The `fs` adapter reads from a local directory (prototype default). The `gcs` adapter
reads from `gs://secdb-config/...` (production). GCS `OBJECT_FINALIZE` publishes to
`secdb-config-changed`, which push-refreshes API + normalizer caches via
`/internal/config-reload`; the 10-minute TTL remains the safety net.

The `OwnershipMap` and `RbacMap` types expose just the queries the rest of the codebase
needs. Callers never see raw YAML.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from app.core.config import Settings, get_settings

if TYPE_CHECKING:
    from app.core.component_registry import ComponentRegistry
    from app.core.wiz_subscription_pillar import WizSubscriptionPillarMap

REFRESH_INTERVAL_SECONDS = 600 # 10 minutes


@dataclass(frozen=True)
class Contact:
    """A named human contact (EM, security POC). Email is optional because the
    seeding spreadsheets only carry display names — emails get filled in over
    time, and downstream code must tolerate `None`."""

    name: str
    email: str | None = None


@dataclass(frozen=True)
class TeamConfig:
    name: str  # canonical key (also the developer-role scope value)
    pillar: str | None = None  # e.g. "product", "retail", "io"
    display_name: str | None = None  # human label shown in UI (e.g. "Order 1")
    jira_project: str | None = None  # JIRA prefix (e.g. "ORD")
    slack: str | None = None
    engineering_manager: Contact | None = None
    security_poc: Contact | None = None
    members: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Pillar:
    id: str  # canonical key
    name: str  # display name


@dataclass(frozen=True)
class OwnershipMap:
    """Immutable snapshot. Reload swaps the whole map atomically."""

    asset_to_team: dict[str, str] = field(default_factory=dict)
    teams: dict[str, TeamConfig] = field(default_factory=dict)
    pillars: dict[str, Pillar] = field(default_factory=dict)
    # Reverse lookup for source-specific identifiers that don't match an asset's
    # canonical id by convention. SonarCloud's project keys are the first user
    #; other sources can join the same map shape later.
    sonar_key_to_asset_id: dict[str, str] = field(default_factory=dict)
    # Repo short names (`product-core`, not `repo:ExampleOrg/product-core`) listed in
    # `excluded_repos` — stamped `excluded`, not `unowned`.
    excluded_repos: frozenset[str] = field(default_factory=frozenset)
    loaded_at: float = 0.0
    # Case-insensitive companion index over `asset_to_team`, scoped to the
    # `repo:<org>/<name>` namespace only. Built once in `__post_init__`; see
    # `team_for_asset` for the why.
    _repo_asset_to_team_lower: dict[str, str] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        # Frozen dataclass: bypass `__setattr__` via `object.__setattr__`.
        object.__setattr__(
            self,
            "_repo_asset_to_team_lower",
            {
                k.lower(): v
                for k, v in self.asset_to_team.items()
                if k.startswith("repo:")
            },
        )

    def team_for_asset(self, asset_id: str) -> str:
        if asset_id.startswith("repo:") and "/" in asset_id:
            _org, _, repo = asset_id.removeprefix("repo:").partition("/")
            if repo in self.excluded_repos:
                return "excluded"
            # Exact match wins. Preserves any pre-existing case-sensitive
            # behaviour for callers passing already-canonical ids and is the
            # fast path on every ingest / re-resolve.
            team = self.asset_to_team.get(asset_id)
            if team is not None:
                return team
            # Belt-and-braces fallback for the `repo:` namespace only: a repo's
            # identity is the `(org, name)` pair regardless of casing, but the
            # asset_id stored on a Finding row can drift in case from
            # `ownership.yaml.assets[*].id` — e.g. legacy rows persisted under
            # a transient empty `GITHUB_ORG` got `repo:exampleorg/...` while the
            # YAML lists `repo:ExampleOrg/...`. Without this lowercase fallback,
            # such rows read back as `unowned`, and the nightly rollup
            # `core_reresolve` flips them back to `unowned` on every pass
            # (the see-saw). The processor canonicalises asset_id at ingest
            # (per the asset re-stamp in `process_snapshot`), so this is the
            # safety net for the window between deploy and the next ingest of
            # each row, plus any path that resolves ownership against a
            # historical asset_id (rollup, admin re-resolve, etc.).
            #
            # Scoped to `repo:` deliberately: Sonar project keys
            # (`sonarproj:` namespace) are case-sensitive identifiers in the
            # upstream system — Sonar treats `Foo` and `foo` as distinct
            # projects — and lowercasing them would create false matches.
            return self._repo_asset_to_team_lower.get(asset_id.lower(), "unowned")
        return self.asset_to_team.get(asset_id, "unowned")

    def teams_for_member(self, email: str) -> set[str]:
        return {t.name for t in self.teams.values() if email in t.members}

    def slack_for_team(self, team: str) -> str | None:
        cfg = self.teams.get(team)
        return cfg.slack if cfg else None

    def teams_in_pillar(self, pillar: str) -> list[str]:
        return [name for name, cfg in self.teams.items() if cfg.pillar == pillar]


@dataclass(frozen=True)
class ScopeMap:
    """Shared scope metadata for executive pillar/application/service expansion."""

    executive_pillar_to_teams: dict[str, tuple[str, ...]] = field(default_factory=dict)
    jira_project_to_teams: dict[str, tuple[str, ...]] = field(default_factory=dict)
    application_to_teams: dict[str, tuple[str, ...]] = field(default_factory=dict)
    service_to_teams: dict[str, tuple[str, ...]] = field(default_factory=dict)
    loaded_at: float = 0.0

    def teams_for_executive_pillar(self, key: str) -> list[str]:
        return list(self.executive_pillar_to_teams.get(key.lower(), ()))

    def teams_for_jira_project(self, key: str) -> list[str]:
        return list(self.jira_project_to_teams.get(key.upper(), ()))

    def teams_for_application(self, key: str) -> list[str]:
        return list(self.application_to_teams.get(key.lower(), ()))

    def teams_for_service(self, key: str) -> list[str]:
        return list(self.service_to_teams.get(key.lower(), ()))


@dataclass(frozen=True)
class RbacMap:
    """Single-flag RBAC config (collapse).

    `admin_emails` is an explicit allowlist — only emails listed here are
    treated as admin. Everyone else passing IAP at the LB sees the dashboard
    as a member; the LB allowlist is the gate on who reaches us at all, so
    there's no group check in code.

    The previous `member_groups` field is gone — there's no in-code group
    check any more. If we later want to require a specific group as an extra
    check, it lands as a one-liner here without churning the wider API.
    """

    admin_emails: frozenset[str] = field(default_factory=frozenset)
    loaded_at: float = 0.0

    def is_admin(self, email: str) -> bool:
        return email in self.admin_emails


class ConfigSource(ABC):
    @abstractmethod
    def read_text(self, name: str) -> str: ...


class _FsSource(ConfigSource):
    def __init__(self, root: Path) -> None:
        self._root = root

    def read_text(self, name: str) -> str:
        return (self._root / name).read_text(encoding="utf-8")


class _GcsSource(ConfigSource):
    def __init__(self, bucket: str) -> None:
        from google.cloud import storage

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)

    def read_text(self, name: str) -> str:
        return self._bucket.blob(name).download_as_text()


def _load_optional_wiz_service_team_map(source: ConfigSource) -> dict[str, str]:
    """Read wiz_service_team_map.yaml; absent in fs/gcs returns {}."""
    from app.core.wiz_auto_map import parse_wiz_service_team_map_text

    try:
        return parse_wiz_service_team_map_text(
            source.read_text("wiz_service_team_map.yaml")
        )
    except FileNotFoundError:
        return {}
    except Exception as exc:
        try:
            from google.api_core.exceptions import NotFound as ApiNotFound
        except ImportError:
            raise
        if isinstance(exc, ApiNotFound):
            return {}
        raise


def _build_source(settings: Settings) -> ConfigSource:
    if settings.config_store == "fs":
        return _FsSource(Path(settings.config_store_fs_root).resolve())
    if settings.config_store == "gcs":
        if not settings.gcs_config_bucket:
            raise RuntimeError("CONFIG_STORE=gcs requires GCS_CONFIG_BUCKET")
        return _GcsSource(settings.gcs_config_bucket)
    raise RuntimeError(f"unknown CONFIG_STORE: {settings.config_store}")


def _parse_contact(raw: dict | list | str | None) -> Contact | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return _parse_contact(raw[0]) if raw else None
    if isinstance(raw, str):
        return Contact(name=raw)
    return Contact(name=raw["name"], email=raw.get("email"))


def _parse_ownership(text: str) -> OwnershipMap:
    raw = yaml.safe_load(text) or {}
    asset_to_team: dict[str, str] = {}
    sonar_key_to_asset_id: dict[str, str] = {}
    for entry in raw.get("assets", []) or []:
        asset_to_team[entry["id"]] = entry["team"]
        # Optional per-source identifier overrides. defines `sonar_project_key`;
        # additional source keys (e.g. `wiz_resource_id`) can be added here without
        # touching the consumer code.
        sonar_key = entry.get("sonar_project_key")
        if sonar_key:
            sonar_key_to_asset_id[str(sonar_key)] = entry["id"]

    pillars: dict[str, Pillar] = {}
    for pid, pcfg in (raw.get("pillars") or {}).items():
        pcfg = pcfg or {}
        pillars[pid] = Pillar(id=pid, name=pcfg.get("name", pid))

    teams: dict[str, TeamConfig] = {}
    for name, cfg in (raw.get("teams") or {}).items():
        cfg = cfg or {}
        teams[name] = TeamConfig(
            name=name,
            pillar=cfg.get("pillar"),
            display_name=cfg.get("display_name"),
            jira_project=cfg.get("jira_project"),
            slack=cfg.get("slack"),
            engineering_manager=_parse_contact(cfg.get("engineering_manager")),
            security_poc=_parse_contact(cfg.get("security_poc")),
            members=frozenset(cfg.get("members") or []),
        )

    excluded = frozenset(str(r) for r in (raw.get("excluded_repos") or []))

    return OwnershipMap(
        asset_to_team=asset_to_team,
        teams=teams,
        pillars=pillars,
        sonar_key_to_asset_id=sonar_key_to_asset_id,
        excluded_repos=excluded,
        loaded_at=time.time(),
    )


def _parse_rbac(text: str) -> RbacMap:
    raw = yaml.safe_load(text) or {}
    admin_emails = frozenset(raw.get("admin_emails") or [])
    return RbacMap(admin_emails=admin_emails, loaded_at=time.time())


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return tuple(out)


def _parse_scope_map(text: str) -> ScopeMap:
    raw = yaml.safe_load(text) or {}
    executive_pillar_to_teams: dict[str, tuple[str, ...]] = {}
    for key, cfg in (raw.get("executive_pillars") or {}).items():
        cfg = cfg or {}
        teams = [str(t) for t in (cfg.get("team_keys") or [])]
        executive_pillar_to_teams[str(key).lower()] = _dedupe(teams)

    application_to_teams: dict[str, tuple[str, ...]] = {}
    for key, cfg in (raw.get("applications") or {}).items():
        cfg = cfg or {}
        teams = [str(t) for t in (cfg.get("teams") or [])]
        application_to_teams[str(key).lower()] = _dedupe(teams)

    service_to_teams: dict[str, tuple[str, ...]] = {}
    for key, cfg in (raw.get("services") or {}).items():
        cfg = cfg or {}
        teams = [str(t) for t in (cfg.get("teams") or [])]
        service_to_teams[str(key).lower()] = _dedupe(teams)

    return ScopeMap(
        executive_pillar_to_teams=executive_pillar_to_teams,
        jira_project_to_teams={},
        application_to_teams=application_to_teams,
        service_to_teams=service_to_teams,
        loaded_at=time.time(),
    )


class ConfigCache:
    """Thread-safe in-memory cache with time-based refresh.

    The cache holds the most recently loaded snapshot. `get_*` returns the snapshot
    immediately and triggers a background refresh if older than the threshold. The
    first call blocks long enough to load both files.
    """

    def __init__(self, source: ConfigSource) -> None:
        self._source = source
        self._lock = threading.RLock()
        self._ownership: OwnershipMap | None = None
        self._rbac: RbacMap | None = None
        self._scope_map: ScopeMap | None = None
        self._component_registry: ComponentRegistry | None = None
        self._wiz_subscription_pillar: WizSubscriptionPillarMap | None = None

    def _stale(self, snapshot_loaded_at: float | None) -> bool:
        return (
            snapshot_loaded_at is None
            or time.time() - snapshot_loaded_at > REFRESH_INTERVAL_SECONDS
        )

    def get_ownership(self) -> OwnershipMap:
        with self._lock:
            if self._ownership is None or self._stale(self._ownership.loaded_at):
                self._ownership = _parse_ownership(self._source.read_text("ownership.yaml"))
            return self._ownership

    def get_rbac(self) -> RbacMap:
        with self._lock:
            if self._rbac is None or self._stale(self._rbac.loaded_at):
                self._rbac = _parse_rbac(self._source.read_text("rbac.yaml"))
            return self._rbac

    def get_scope_map(self) -> ScopeMap:
        with self._lock:
            if self._scope_map is None or self._stale(self._scope_map.loaded_at):
                try:
                    text = self._source.read_text("component_scope.yaml")
                    self._scope_map = _parse_scope_map(text)
                except FileNotFoundError:
                    self._scope_map = ScopeMap(loaded_at=time.time())
            return self._scope_map

    def get_component_registry(self) -> ComponentRegistry:
        from app.core.component_registry import (
            enrich_registry_wiz_indexes,
            parse_component_registry,
        )
        with self._lock:
            if self._component_registry is None or self._stale(
                self._component_registry.loaded_at
            ):
                text = self._source.read_text("component_registry.yaml")
                reg = parse_component_registry(text)
                supplemental = _load_optional_wiz_service_team_map(self._source)
                self._component_registry = enrich_registry_wiz_indexes(reg, supplemental)
            return self._component_registry

    def get_wiz_subscription_pillar(self) -> WizSubscriptionPillarMap:
        from app.core.wiz_subscription_pillar import (
            WizSubscriptionPillarMap,
            parse_wiz_subscription_pillar,
        )

        with self._lock:
            if self._wiz_subscription_pillar is None or self._stale(
                self._wiz_subscription_pillar.loaded_at
            ):
                try:
                    text = self._source.read_text("wiz_subscription_pillar.yaml")
                    self._wiz_subscription_pillar = parse_wiz_subscription_pillar(text)
                except FileNotFoundError:
                    self._wiz_subscription_pillar = WizSubscriptionPillarMap(
                        loaded_at=time.time()
                    )
            return self._wiz_subscription_pillar

    def force_reload(self) -> None:
        with self._lock:
            self._ownership = None
            self._rbac = None
            self._scope_map = None
            self._component_registry = None
            self._wiz_subscription_pillar = None


_cache: ConfigCache | None = None


def get_config_cache() -> ConfigCache:
    global _cache
    if _cache is None:
        _cache = ConfigCache(_build_source(get_settings()))
    return _cache


def reset_config_cache_for_tests() -> None:
    global _cache
    _cache = None
