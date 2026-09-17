"""api_tokens schema for MCP personal tokens

Revision ID: b2c4e8f91a03
Revises: ad807828ff66
Create Date: 2026-05-18 20:00:00.000000

The initial api_tokens table was committed up-front but never written to.
We replace it with the self-service MCP token shape (SHA-256 hash, optional
expiry, active_role snapshot, prefix for list UI).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c4e8f91a03"
down_revision: str | Sequence[str] | None = "ad807828ff66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index(op.f("ix_api_tokens_email"), table_name="api_tokens")
    op.drop_table("api_tokens")

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("active_role", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_api_tokens_email"), "api_tokens", ["email"], unique=False)
    op.create_index(
        "ix_api_tokens_email_active",
        "api_tokens",
        ["email"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_api_tokens_email_active", table_name="api_tokens")
    op.drop_index(op.f("ix_api_tokens_email"), table_name="api_tokens")
    op.drop_table("api_tokens")

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=256), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("teams", sa.ARRAY(sa.String()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_api_tokens_email"), "api_tokens", ["email"], unique=False)
