"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-13

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coordinators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_coordinators_username"),
    )
    op.create_index("ix_coordinators_username", "coordinators", ["username"], unique=True)

    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_areas_name"),
    )
    op.create_index("ix_areas_name", "areas", ["name"], unique=True)

    op.create_table(
        "donors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manage_token_hash", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("blood_group", sa.String(length=4), nullable=False),
        sa.Column("phone_normalized", sa.String(length=20), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=False),
        sa.Column("last_donation_date", sa.Date(), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unverified"),
        sa.Column("is_over_18", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consent_verify", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verify_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("phone_normalized", name="uq_donors_phone"),
        sa.UniqueConstraint("manage_token_hash", name="uq_donors_manage_token"),
    )
    op.create_index("ix_donors_manage_token_hash", "donors", ["manage_token_hash"], unique=True)
    op.create_index("ix_donors_phone_normalized", "donors", ["phone_normalized"], unique=True)
    op.create_index("ix_donors_blood_group", "donors", ["blood_group"])
    op.create_index("ix_donors_area_id", "donors", ["area_id"])
    op.create_index("ix_donors_status", "donors", ["status"])

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_token", sa.String(length=64), nullable=False),
        sa.Column("blood_group", sa.String(length=4), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("hospital_name", sa.String(length=200), nullable=False),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id"), nullable=False),
        sa.Column("needed_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requester_name", sa.String(length=120), nullable=False),
        sa.Column("requester_phone_normalized", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("consent_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("reject_reason", sa.String(length=500), nullable=True),
        sa.Column("verified_by_id", sa.Integer(), sa.ForeignKey("coordinators.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_token", name="uq_requests_public_token"),
    )
    op.create_index("ix_requests_public_token", "requests", ["public_token"], unique=True)
    op.create_index("ix_requests_blood_group", "requests", ["blood_group"])
    op.create_index("ix_requests_area_id", "requests", ["area_id"])
    op.create_index("ix_requests_needed_by", "requests", ["needed_by"])
    op.create_index("ix_requests_status", "requests", ["status"])
    op.create_index("ix_requests_source_ip", "requests", ["source_ip"])

    op.create_table(
        "contact_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=False),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=False),
        sa.Column("coordinator_id", sa.Integer(), sa.ForeignKey("coordinators.id"), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contact_attempts_donor_id", "contact_attempts", ["donor_id"])
    op.create_index("ix_contact_attempts_request_id", "contact_attempts", ["request_id"])
    op.create_index("ix_contact_attempts_outcome", "contact_attempts", ["outcome"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("coordinator_id", sa.Integer(), sa.ForeignKey("coordinators.id"), nullable=True),
        sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("requests.id"), nullable=True),
        sa.Column("contact_attempt_id", sa.Integer(), sa.ForeignKey("contact_attempts.id"), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_donor_id", "audit_log", ["donor_id"])
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("username_hash", sa.String(length=128), nullable=False),
        sa.Column("coordinator_id", sa.Integer(), sa.ForeignKey("coordinators.id"), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_login_attempts_username_hash", "login_attempts", ["username_hash"])
    op.create_index("ix_login_attempts_username", "login_attempts", ["username"])
    op.create_index("ix_login_attempts_coordinator_id", "login_attempts", ["coordinator_id"])
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])

    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("donor_id", sa.Integer(), sa.ForeignKey("donors.id"), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=True),
        sa.Column("pending_code_hash", sa.String(length=128), nullable=True),
        sa.Column("pending_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("donor_id", name="uq_telegram_links_donor"),
    )


def downgrade() -> None:
    op.drop_table("telegram_links")
    op.drop_table("login_attempts")
    op.drop_table("audit_log")
    op.drop_table("contact_attempts")
    op.drop_table("requests")
    op.drop_table("donors")
    op.drop_table("areas")
    op.drop_table("coordinators")
