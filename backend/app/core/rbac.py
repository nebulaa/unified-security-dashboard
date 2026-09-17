"""Single-flag authorization: `is_admin` derived from `rbac.yaml.admin_emails`.

The only authorization question on every request is binary: "is this email in
`rbac.yaml.admin_emails`?"

Anyone who reaches the API has already passed IAP at the LB — IAP is the
gate on access. In code we just look at the email. Admins get `/admin` and
the dedicated Trivy-in-SonarCloud opt-in; everyone else gets the same
dashboard the admin sees, minus those two surfaces.

The `Role` enum, `X-Active-Role` header, `active_role`/`default_role`/
`roles`/`teams_by_role` fields, and the page-shaped `view=...` narrowing
they ran on are all gone. Page-level rollups (Developer / Platform /
Executive) are pure frontend constructs now — they pass `?team=` and
`?source=` like any other caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config_store import get_config_cache
from app.core.display_name import display_name_from_email
from app.core.identity import Identity


@dataclass
class UserContext:
    """Per-request authorization view of one caller.

    Only two fields matter downstream: `email` (for audit + token bookkeeping)
    and `is_admin` (the single capability flag). Held as a dataclass rather
    than a flat dict so future read-only properties (e.g. `is_admin_for(...)`)
    can land without churning every callsite.
    """

    identity: Identity
    is_admin: bool

    @property
    def email(self) -> str:
        return self.identity.email

    @property
    def name(self) -> str:
        if self.identity.name:
            return self.identity.name
        return display_name_from_email(self.identity.email)


def build_user_context(
    identity: Identity,
    session: Session,  # noqa: ARG001 — kept for signature compat with callers
) -> UserContext:
    rbac = get_config_cache().get_rbac()
    return UserContext(identity=identity, is_admin=rbac.is_admin(identity.email))
