"""Domain enums.

Severity, Status, EventType become Postgres ENUM types via SQLAlchemy. Source stays a
plain string column — adding a new scanner should not require a migration.

Status / EventType shape is anchored in (auto-close lifecycle) and
(`ownership_changed`).
"""

from __future__ import annotations

from enum import StrEnum


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class Status(StrEnum):
    open = "open"
    triaged = "triaged"
    in_progress = "in_progress"
    fixed = "fixed"
    auto_closed = "auto_closed"
    risk_accepted = "risk_accepted"
    suppressed = "suppressed"

    @classmethod
    def open_set(cls) -> set[Status]:
        return {cls.open, cls.triaged, cls.in_progress}

    @classmethod
    def closed_set(cls) -> set[Status]:
        return {cls.fixed, cls.auto_closed, cls.risk_accepted, cls.suppressed}


class EventType(StrEnum):
    discovered = "discovered"
    severity_changed = "severity_changed"
    status_changed = "status_changed"
    title_changed = "title_changed"
    description_changed = "description_changed"
    fixed = "fixed"
    suppressed = "suppressed"
    auto_closed = "auto_closed"
    reopened = "reopened"
    ownership_changed = "ownership_changed"


KNOWN_SOURCES: frozenset[str] = frozenset(
    {
        "dependabot",
        "sonarcloud",
        # SonarCloud-hosted external Trivy issues. Same poller/lifecycle as
        # `sonarcloud`, but a separate logical source so the dashboard can
        # hide them from /developer, /executive, /platform and surface them
        # only in the dedicated /admin "Trivy issues in SonarCloud" section.
        # See the mapper module for the rule-prefix detection rule.
        "sonarcloud_trivy",
        "trivy",
        "wiz",
        "nuclei",
        "vanta",
        "pentest",
    }
)
