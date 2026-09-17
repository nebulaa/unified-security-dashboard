"""add findings.upstream_url for Wiz portal deep links

Revision ID: f3a8c1d02e4b
Revises: e1f4a9c2b8d0
Create Date: 2026-06-02

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f3a8c1d02e4b"
down_revision = "e1f4a9c2b8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("findings", sa.Column("upstream_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("findings", "upstream_url")
