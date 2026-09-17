"""Hot-reload config caches on GCS publish."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config_store import get_config_cache
from app.core.db import session_scope
from app.core.jira_pentest import get_jira_pentest_cache
from app.core.policy import get_policy_cache
from app.internal.ownership_reresolve import core_reresolve, maybe_trigger_rollup_backfill

log = logging.getLogger("secdb.config_reload")


def reload_caches() -> None:
    """Refresh in-memory config/policy only (API + normalizer)."""
    get_config_cache().force_reload()
    get_policy_cache().force_reload()
    get_jira_pentest_cache().force_reload()


def reload_all_config(*, config_kind: str | None = None) -> dict[str, Any]:
    """Reload caches; re-resolve owner_team when ownership config changed (API path)."""
    reload_caches()
    result: dict[str, Any] = {
        "status": "reloaded",
        "owner_team_updates": 0,
        "rollup_triggered": False,
    }

    if config_kind is not None and config_kind != "ownership":
        return result

    ownership = get_config_cache().get_ownership()
    with session_scope() as session:
        rr = core_reresolve(session, ownership, actor="system:config_reload")
    result["owner_team_updates"] = rr.updated
    result["rollup_triggered"] = maybe_trigger_rollup_backfill(
        rr.updated, async_mode=True
    )
    log.info(
        "config.reload complete owner_team_updates=%d rollup_triggered=%s",
        rr.updated,
        result["rollup_triggered"],
    )
    return result
