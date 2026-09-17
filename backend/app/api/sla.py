"""SLA computation helpers — read-time only, never persisted (D8).

A finding's SLA window comes from `sla.yaml` keyed by severity. A finding is
"breached" when `now - sla_started_at > window`. `info` (window=null) is never
breached. Closed findings (`fixed`, `auto_closed`, `risk_accepted`, `suppressed`)
are not subject to SLA — the clock stops at closure.

The age/SLA anchor is `Finding.sla_started_at`, which prefers (in order):
  1. `upstream_created_at` — source-system creation timestamp (true age)
  2. `first_seen_at` — first ingest by us (legacy fallback for pre-migration rows)

This means a 6-month-old GitHub alert that we ingested yesterday is correctly
shown as 6 months old, not 1 day old.

`reopened_at` is deliberately NOT in this precedence (anymore). It used to win
over `upstream_created_at` on the rationale that "a re-introduced vulnerability
gets a fresh SLA window", but in practice our reopen lifecycle (auto_closed ->
open) almost always fires after either (a) an absent-detection bug like the
SonarCloud multi-org cross-contamination that auto-closed 1k+ valid findings
overnight (commit 8d11948), or (b) a scanner-side blip where Sonar dropped
issues from a snapshot and re-added them on the next scan. Neither case is a
real re-introduction; both reset the age clock to "moments ago" and make every
old finding look brand new — exactly the "everything is 3 hours old" symptom
the cloud was exhibiting after the multi-org fix landed and 1k Sonar findings
got bulk-reopened in a single poll.

Sonar's own `creationDate` is the canonical source-of-truth for "when did this
vulnerability first appear?" — and it survives our auto_close + reopen cycle
intact (same `issue.key`, same `creationDate`). For a true re-introduction
(issue closed in Sonar, then re-detected later), Sonar generates a fresh issue
with a fresh `creationDate`; `upstream_created_at` naturally tracks that. So
dropping `reopened_at` from the anchor is correct in both cases.

The nightly `daily_metrics` rollup (`app/jobs/rollup.py`) has always anchored on
`coalesce(upstream_created_at, first_seen_at)` — amendment
2026-05-21 and the pinned test `test_rollup.py::…anchor should be
upstream-created (older), not the later reopened_at`. Bringing live `/findings`
+ `/metrics` in line with the rollup eliminates the "live age says 3h, trend
chart says 100d" inconsistency operators were seeing in cloud.

`reopened_at` is still PERSISTED (used by `processor.py` to time the reopen
event for the audit log + by /admin to flag flappy findings), it's just no
longer the age anchor.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import Severity, Status
from app.core.policy import SlaPolicy


def is_open(status: Status) -> bool:
    return status in Status.open_set()


def sla_started_at(
    *,
    upstream_created_at: datetime | None,
    first_seen_at: datetime,
) -> datetime:
    """The wall-clock anchor used for both age display and SLA breach checks."""
    return upstream_created_at or first_seen_at


def age_seconds(anchor: datetime, now: datetime | None = None) -> float:
    return ((now or datetime.now(UTC)) - anchor).total_seconds()


def is_breached(
    sla: SlaPolicy,
    severity: Severity,
    status: Status,
    anchor: datetime,
    now: datetime | None = None,
) -> bool:
    if not is_open(status):
        return False
    window = sla.window_seconds(severity.value)
    if window is None:
        return False
    return age_seconds(anchor, now) > window
