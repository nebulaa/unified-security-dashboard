"""`coverage.yaml` loader — thresholds, key projects, exceptions.

Same ConfigSource adapter and 10-minute refresh as `policy.py`, so an operator
editing an exception in the config bucket takes effect without a deploy.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date

import yaml

from app.core.config_store import ConfigSource, _build_source

REFRESH_INTERVAL_SECONDS = 600

DEFAULT_GREEN_PCT = 95.0
DEFAULT_AMBER_PCT = 85.0
DEFAULT_STALENESS_HOURS = 36

ALL_METRICS = "*"
DEFAULT_LAYERS = ("platform", "workload", "code")


@dataclass(frozen=True)
class CoverageException:
    """A time-boxed removal from the denominator."""

    item_type: str
    item_id: str
    metric: str
    owner: str
    reason: str
    expires: date

    def is_active(self, today: date) -> bool:
        return self.expires >= today

    def covers(self, item_type: str, item_id: str, metric_key: str) -> bool:
        if self.item_type != item_type or self.item_id != item_id:
            return False
        return self.metric in (ALL_METRICS, metric_key)


@dataclass(frozen=True)
class ScopeRule:
    folders: tuple[str, ...] = ()
    name_patterns: tuple[str, ...] = ()
    labels: tuple[tuple[str, str], ...] = ()
    exclude_name_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class InventoryConfig:
    gcp_production: ScopeRule = ScopeRule()
    aws_production: ScopeRule = ScopeRule()
    repo_pushed_within_days: int = 90
    vm_min_age_hours: int = 24


@dataclass(frozen=True)
class ProjectConfig:
    key: str
    label: str
    flagship: bool = False
    code_topics: tuple[str, ...] = ()
    exclude_code_topics: tuple[str, ...] = ()
    cloud: ScopeRule = ScopeRule()


@dataclass(frozen=True)
class CoverageConfig:
    green_pct: float = DEFAULT_GREEN_PCT
    amber_pct: float = DEFAULT_AMBER_PCT
    staleness_hours: int = DEFAULT_STALENESS_HOURS
    enabled_layers: tuple[str, ...] = DEFAULT_LAYERS
    inventory: InventoryConfig = InventoryConfig()
    projects: tuple[ProjectConfig, ...] = ()
    exceptions: tuple[CoverageException, ...] = ()
    loaded_at: float = 0.0

    def active_exceptions(self, today: date) -> tuple[CoverageException, ...]:
        return tuple(e for e in self.exceptions if e.is_active(today))

    def collects_cloud(self) -> bool:
        return any(layer in {"platform", "workload"} for layer in self.enabled_layers)


def _parse_date(value: object, *, item_id: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"coverage exception {item_id!r}: invalid expires {value!r}")


def _scope_rule(raw: dict | None, *, folder_key: str = "folders") -> ScopeRule:
    raw = raw or {}
    labels = raw.get("labels") or raw.get("tags") or {}
    return ScopeRule(
        folders=tuple(str(v) for v in (raw.get(folder_key) or ())),
        name_patterns=tuple(str(v).lower() for v in (raw.get("name_patterns") or ())),
        labels=tuple((str(k), str(v)) for k, v in labels.items()),
        exclude_name_patterns=tuple(
            str(v).lower() for v in (raw.get("exclude_name_patterns") or ())
        ),
    )


def parse_coverage_config(text: str) -> CoverageConfig:
    raw = yaml.safe_load(text) or {}

    thresholds = raw.get("thresholds") or {}
    green = float(thresholds.get("green_pct", DEFAULT_GREEN_PCT))
    amber = float(thresholds.get("amber_pct", DEFAULT_AMBER_PCT))
    if amber > green:
        raise ValueError(f"coverage thresholds: amber_pct {amber} above green_pct {green}")

    inventory_raw = raw.get("inventory") or {}
    account_production = (
        ((inventory_raw.get("cloud_accounts") or {}).get("production")) or {}
    )
    repo_eligibility = (inventory_raw.get("repos") or {}).get("eligibility") or {}
    vm_rules = inventory_raw.get("vms") or {}
    inventory = InventoryConfig(
        gcp_production=_scope_rule(account_production.get("gcp")),
        aws_production=_scope_rule(
            account_production.get("aws"), folder_key="organizational_units"
        ),
        repo_pushed_within_days=int(repo_eligibility.get("pushed_within_days", 90)),
        vm_min_age_hours=int(vm_rules.get("min_age_hours", 24)),
    )

    projects: list[ProjectConfig] = []
    for key, cfg in (raw.get("projects") or {}).items():
        cfg = cfg or {}
        code = cfg.get("code") or {}
        projects.append(
            ProjectConfig(
                key=str(key),
                label=str(cfg.get("label", key)),
                flagship=bool(cfg.get("flagship", False)),
                code_topics=tuple(str(v).lower() for v in (code.get("github_topics") or ())),
                exclude_code_topics=tuple(
                    str(v).lower() for v in (code.get("exclude_github_topics") or ())
                ),
                cloud=_scope_rule(cfg.get("cloud"), folder_key="gcp_folders"),
            )
        )

    exceptions: list[CoverageException] = []
    for entry in raw.get("exceptions") or []:
        entry = entry or {}
        item_id = str(entry.get("item_id", ""))
        missing = [f for f in ("item_type", "item_id", "owner", "reason", "expires") if not entry.get(f)]
        if missing:
            raise ValueError(
                f"coverage exception {item_id or '<no id>'}: missing {', '.join(missing)}"
            )
        exceptions.append(
            CoverageException(
                item_type=str(entry["item_type"]),
                item_id=item_id,
                metric=str(entry.get("metric", ALL_METRICS)),
                owner=str(entry["owner"]),
                reason=str(entry["reason"]),
                expires=_parse_date(entry["expires"], item_id=item_id),
            )
        )

    raw_layers = raw.get("enabled_layers")
    if raw_layers is None:
        enabled_layers = DEFAULT_LAYERS
    else:
        enabled_layers = tuple(str(v) for v in raw_layers)
        unknown = [layer for layer in enabled_layers if layer not in DEFAULT_LAYERS]
        if unknown:
            raise ValueError(f"coverage enabled_layers: unknown {unknown}")

    return CoverageConfig(
        green_pct=green,
        amber_pct=amber,
        staleness_hours=int(raw.get("staleness_hours", DEFAULT_STALENESS_HOURS)),
        enabled_layers=enabled_layers,
        inventory=inventory,
        projects=tuple(projects),
        exceptions=tuple(exceptions),
        loaded_at=time.time(),
    )


class CoverageConfigCache:
    def __init__(self, source: ConfigSource) -> None:
        self._source = source
        self._lock = threading.RLock()
        self._config: CoverageConfig | None = None

    def get(self) -> CoverageConfig:
        with self._lock:
            stale = (
                self._config is None
                or time.time() - self._config.loaded_at > REFRESH_INTERVAL_SECONDS
            )
            if stale:
                try:
                    self._config = parse_coverage_config(self._source.read_text("coverage.yaml"))
                except FileNotFoundError:
                    self._config = CoverageConfig(loaded_at=time.time())
            assert self._config is not None
            return self._config

    def force_reload(self) -> None:
        with self._lock:
            self._config = None


_cache: CoverageConfigCache | None = None


def get_coverage_config_cache() -> CoverageConfigCache:
    global _cache
    if _cache is None:
        from app.core.config import get_settings

        _cache = CoverageConfigCache(_build_source(get_settings()))
    return _cache


def get_coverage_config() -> CoverageConfig:
    return get_coverage_config_cache().get()


def reset_coverage_config_for_tests() -> None:
    global _cache
    _cache = None
