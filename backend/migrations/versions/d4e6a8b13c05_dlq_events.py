"""dlq_events table for ingest dead-letter handling

Revision ID: d4e6a8b13c05
Revises: b2c4e8f91a03
Create Date: 2026-05-20 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e6a8b13c05"
down_revision: str | Sequence[str] | None = "b2c4e8f91a03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dlq_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("poll_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("raw_uri", sa.Text(), nullable=True),
        sa.Column("envelope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("delivery_attempt", sa.Integer(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id", name="uq_dlq_events_message_id"),
    )
    op.create_index(
        "ix_dlq_events_unresolved",
        "dlq_events",
        ["received_at"],
        unique=False,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_dlq_events_unresolved", table_name="dlq_events")
    op.drop_table("dlq_events")
