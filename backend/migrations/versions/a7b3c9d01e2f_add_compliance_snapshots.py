"""add compliance_snapshots table

Revision ID: a7b3c9d01e2f
Revises: f3a8c1d02e4b
Create Date: 2026-06-05

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7b3c9d01e2f"
down_revision = "f3a8c1d02e4b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("framework", sa.String(length=32), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=256), nullable=False),
        sa.Column("scope_name", sa.String(length=512), nullable=True),
        sa.Column("pillar", sa.String(length=32), nullable=True),
        sa.Column("score_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("controls_pass", sa.Integer(), nullable=True),
        sa.Column("controls_fail", sa.Integer(), nullable=True),
        sa.Column("controls_total", sa.Integer(), nullable=True),
        sa.Column("polled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_ref", sa.String(length=512), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_date",
            "framework",
            "scope_type",
            "scope_id",
            name="uq_compliance_snapshots_day_framework_scope",
        ),
    )
    op.create_index(
        "ix_compliance_snapshots_date_framework_pillar",
        "compliance_snapshots",
        ["snapshot_date", "framework", "pillar"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_snapshots_framework_scope_date",
        "compliance_snapshots",
        ["framework", "scope_type", "scope_id", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_compliance_snapshots_framework_scope_date",
        table_name="compliance_snapshots",
    )
    op.drop_index(
        "ix_compliance_snapshots_date_framework_pillar",
        table_name="compliance_snapshots",
    )
    op.drop_table("compliance_snapshots")
