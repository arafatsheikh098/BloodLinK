"""add request_attempts table (F5.3, F5.4 rate limiting)

Revision ID: 0002_request_attempts
Revises: 0001_initial
Create Date: 2026-10-13

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_request_attempts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "request_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("requester_phone_hash", sa.String(length=128), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_request_attempts_source_ip", "request_attempts", ["source_ip"])
    op.create_index(
        "ix_request_attempts_requester_phone_hash",
        "request_attempts",
        ["requester_phone_hash"],
    )
    op.create_index("ix_request_attempts_created_at", "request_attempts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_request_attempts_created_at", table_name="request_attempts")
    op.drop_index("ix_request_attempts_requester_phone_hash", table_name="request_attempts")
    op.drop_index("ix_request_attempts_source_ip", table_name="request_attempts")
    op.drop_table("request_attempts")
