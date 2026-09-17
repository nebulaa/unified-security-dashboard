"""Finding scope = opt-in-only admin-only-source gating. Nothing else.

Authorization collapsed to a single `is_admin` flag (see `app.core.rbac`),
and the page-shaped `?view=...` narrowing that previously rode shotgun is
gone. Pages narrow via `?team=` / `?source=` like any other caller.

`ADMIN_ONLY_SOURCES` (today: `sonarcloud_trivy`) are excluded from EVERY
query by default, regardless of who is asking. The dedicated `/admin`
"Trivy in SonarCloud" section is the sole surface where they appear, and it
opts back in by explicitly passing `include_admin_only_sources=True` on the
route handler that backs it. This is opt-in, not role-gated: even an admin
calling the executive KPI endpoint never sees Trivy-in-Sonar inflate the
totals.

The admin check still lives on the *request* side in `routes_findings.py` —
non-admin callers that pass `?source=sonarcloud_trivy` get a 403, so a
misconfigured client fails loudly instead of silently returning an empty
list.
"""

from __future__ import annotations

from sqlalchemy import Select

from app.core.models import Finding
from app.core.rbac import UserContext

# Sources that only the dedicated /admin Trivy-in-Sonar section may surface.
# `sonarcloud_trivy` is SonarCloud-hosted external Trivy issues — they have a
# different lifecycle and triage owner; surfacing them in any non-/admin
# surface would inflate counts and double-count against teams whose Trivy
# findings are tracked elsewhere.
ADMIN_ONLY_SOURCES: frozenset[str] = frozenset({"sonarcloud_trivy"})


def apply_finding_scope(
    query: Select,
    user: UserContext,  # noqa: ARG001 — kept for API stability with existing call sites
    *,
    include_admin_only_sources: bool = False,
) -> Select:
    """Default-exclude `ADMIN_ONLY_SOURCES`; opt in with the kwarg.

    `user` is retained on the signature so that adding a future, narrowly
    scoped per-email opt-in (e.g. a "Trivy in SonarCloud" widget on the
    admin page) doesn't churn every call site. Today it is not consulted —
    the gating is purely a property of the calling surface.
    """
    if not include_admin_only_sources:
        return query.where(Finding.source.notin_(ADMIN_ONLY_SOURCES))
    return query
