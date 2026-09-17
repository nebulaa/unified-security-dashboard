"""add upstream_created_at and reopened_at

Revision ID: ad807828ff66
Revises: 7a5850d37d94
Create Date: 2026-05-15 19:38:43.924344

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ad807828ff66'
down_revision: str | Sequence[str] | None = '7a5850d37d94'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "findings",
        sa.Column("upstream_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "findings",
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing rows keep `upstream_created_at = NULL`. The next poll will fill in
    # the real GitHub `alert.created_at`. Until then, the SLA helper falls back to
    # `first_seen_at`, which preserves prior behavior.


def downgrade() -> None:
    op.drop_column("findings", "reopened_at")
    op.drop_column("findings", "upstream_created_at")
