"""add findings.wiz_category column

Revision ID: e1f4a9c2b8d0
Revises: d4e6a8b13c05
Create Date: 2026-05-21 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f4a9c2b8d0"
down_revision: str | Sequence[str] | None = "d4e6a8b13c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("wiz_category", sa.String(length=64), nullable=True))
    op.create_index("ix_findings_wiz_category", "findings", ["wiz_category"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_findings_wiz_category", table_name="findings")
    op.drop_column("findings", "wiz_category")
