"""Shared types for the normalizer pipeline.

`NormalizedFinding` is the source-agnostic shape every per-source mapper produces.
The snapshot processor (`processor.process_snapshot`) consumes it and never branches
on `source` for any field semantics — adding a new source means writing a new mapper
that emits this shape, no processor changes required.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.enums import Severity


class NormalizedFinding(BaseModel):
    """The shape produced by every per-source mapper. Source-agnostic from here on."""

    id: UUID
    source: str
    native_id: str
    title: str
    description: str
    severity: Severity
    cve_id: str | None = None
    cwe_id: str | None = None
    asset_id: str
    asset_type: str
    asset_root: str
    asset_display: str
    correlation_group_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    # Source-system creation timestamp. Mappers MUST emit this when the upstream
    # exposes one; the SLA clock anchors on it (per Finding.sla_started_at).
    upstream_created_at: datetime | None = None
    wiz_category: str | None = None
    upstream_url: str | None = None
    # When set, the snapshot processor uses this instead of owner_resolver(asset_id).
    # Jira pentest findings stamp team from Jira labels.
    owner_team: str | None = None
