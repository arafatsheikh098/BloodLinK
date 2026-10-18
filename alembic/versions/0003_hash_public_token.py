"""hash public_token at rest (F11.1)

We previously stored the tracking URL token in plaintext in the
``requests.public_token`` column. Anyone with read access to the DB
could then use any active token to view / cancel a request.

Replace the plaintext column with a SHA-256 hash column so the DB
no longer contains any active tracking URL. The plaintext token is
only ever held by the requester, who receives it in the success
page after creating a request.

This migration assumes a pre-launch codebase with no real data.
On a populated database, you would need to backfill the hash from
the plaintext before dropping the column; we don't ship that
variant because deploying the new code without this migration
would already be broken (the code reads/writes ``public_token_hash``).

We use ``batch_alter_table`` so the migration works on SQLite
(test environment) as well as Postgres (production).

Revision ID: 0003_hash_public_token
Revises: 0002_request_attempts
Create Date: 2026-10-13

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_hash_public_token"
down_revision: str | None = "0002_request_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the plaintext column and the unique constraint / index that
    # were created in 0001_initial. batch_alter_table is required for
    # SQLite (which doesn't support DROP CONSTRAINT), and is a no-op
    # improvement on Postgres.
    with op.batch_alter_table("requests") as batch_op:
        batch_op.drop_constraint("uq_requests_public_token", type_="unique")
        batch_op.drop_index("ix_requests_public_token")
        batch_op.drop_column("public_token")
        # Add the new hash column (NULL-able; new code always writes it).
        batch_op.add_column(
            sa.Column("public_token_hash", sa.String(length=128), nullable=True)
        )
        batch_op.create_index(
            "ix_requests_public_token_hash",
            ["public_token_hash"],
            unique=True,
        )
        batch_op.create_unique_constraint(
            "uq_requests_public_token_hash", ["public_token_hash"]
        )


def downgrade() -> None:
    with op.batch_alter_table("requests") as batch_op:
        batch_op.drop_constraint(
            "uq_requests_public_token_hash", type_="unique"
        )
        batch_op.drop_index("ix_requests_public_token_hash")
        batch_op.drop_column("public_token_hash")
        batch_op.add_column(
            sa.Column("public_token", sa.String(length=64), nullable=True)
        )
        batch_op.create_index(
            "ix_requests_public_token", ["public_token"], unique=True
        )
        batch_op.create_unique_constraint(
            "uq_requests_public_token", ["public_token"]
        )
