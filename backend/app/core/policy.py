"""Policy loaders — `auto_close.yaml` (per-source thresholds) and `sla.yaml`.

Both are config files, not application data. Loaded from the same `ConfigStore` adapter
the rest of the codebase uses (fs locally, gcs in prod). Cached in-process; refreshed
on the same 10-minute fallback as ownership/rbac.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

import yaml

from app.core.config_store import ConfigSource, _build_source

REFRESH_INTERVAL_SECONDS = 600


def _parse_duration(s: str | None) -> int | None:
    """Parse `7d`, `30d`, `12h`, `null` -> seconds (or None for never)."""
    if s is None:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*([dhm])\s*", s)
    if not match:
        raise ValueError(f"invalid duration: {s!r}")
    n, unit = int(match.group(1)), match.group(2)
    return n * {"d": 86_400, "h": 3_600, "m": 60}[unit]


@dataclass(frozen=True)
class AutoCloseThresholds:
    """consecutive_misses threshold per source. `None` = never auto-close."""

    by_source: dict[str, int | None] = field(default_factory=dict)
    loaded_at: float = 0.0

    def threshold_for(self, source: str) -> int | None:
        return self.by_source.get(source)


@dataclass(frozen=True)
class SlaPolicy:
    """SLA window per severity, in seconds. `None` = no SLA (e.g. info)."""

    by_severity: dict[str, int | None] = field(default_factory=dict)
    loaded_at: float = 0.0

    def window_seconds(self, severity: str) -> int | None:
        return self.by_severity.get(severity)


class PolicyCache:
    def __init__(self, source: ConfigSource) -> None:
        self._source = source
        self._lock = threading.RLock()
        self._auto_close: AutoCloseThresholds | None = None
        self._sla: SlaPolicy | None = None

    def _stale(self, loaded_at: float | None) -> bool:
        return loaded_at is None or time.time() - loaded_at > REFRESH_INTERVAL_SECONDS

    def get_auto_close(self) -> AutoCloseThresholds:
        with self._lock:
            if self._auto_close is None or self._stale(self._auto_close.loaded_at):
                raw = yaml.safe_load(self._source.read_text("auto_close.yaml")) or {}
                self._auto_close = AutoCloseThresholds(
                    by_source=dict((raw.get("auto_close") or {}).items()),
                    loaded_at=time.time(),
                )
            return self._auto_close

    def get_sla(self) -> SlaPolicy:
        with self._lock:
            if self._sla is None or self._stale(self._sla.loaded_at):
                raw = yaml.safe_load(self._source.read_text("sla.yaml")) or {}
                self._sla = SlaPolicy(
                    by_severity={
                        sev: _parse_duration(window)
                        for sev, window in (raw.get("sla") or {}).items()
                    },
                    loaded_at=time.time(),
                )
            return self._sla

    def force_reload(self) -> None:
        with self._lock:
            self._auto_close = None
            self._sla = None


_cache: PolicyCache | None = None


def get_policy_cache() -> PolicyCache:
    from app.core.config import get_settings

    global _cache
    if _cache is None:
        _cache = PolicyCache(_build_source(get_settings()))
    return _cache


def reset_policy_cache_for_tests() -> None:
    global _cache
    _cache = None
