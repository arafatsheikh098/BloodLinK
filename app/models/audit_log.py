"""Audit log for coordinator actions (F11.1)."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditAction(str, Enum):
    # Coordinator actions on donors
    DONOR_VERIFY = "donor_verify"
    DONOR_SUSPEND = "donor_suspend"
    DONOR_UNSUSPEND = "donor_unsuspend"
    DONOR_PHONE_REVEAL = "donor_phone_reveal"
    DONOR_REGENERATE_LINK = "donor_regenerate_link"
    DONOR_RECORD_DONATION = "donor_record_donation"
    DONOR_SELF_DELETE = "donor_self_delete"
    # Coordinator actions on requests
    REQUEST_VERIFY = "request_verify"
    REQUEST_REJECT = "request_reject"
    REQUEST_CANCEL = "request_cancel"
    # Matching / contact
    CONTACT_ATTEMPT = "contact_attempt"
    # Telegram
    TELEGRAM_LINK_REQUEST = "telegram_link_request"
    TELEGRAM_LINK_COMPLETE = "telegram_link_complete"
    TELEGRAM_NOTIFY_SENT = "telegram_notify_sent"
    TELEGRAM_NOTIFY_FAILED = "telegram_notify_failed"
    TELEGRAM_CALLBACK_ACCEPT = "telegram_callback_accept"
    TELEGRAM_CALLBACK_DECLINE = "telegram_callback_decline"
    TELEGRAM_CALLBACK_REJECTED = "telegram_callback_rejected"
    # Areas
    AREA_CREATE = "area_create"
    AREA_RENAME = "area_rename"
    AREA_DEACTIVATE = "area_deactivate"
    # Login
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    LOGOUT = "logout"
    # Privacy
    PURGE_RUN = "purge_run"


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: int | None = Field(default=None, primary_key=True)
    action: str = Field(index=True, max_length=40)
    actor_kind: str = Field(max_length=16)  # "coordinator", "donor", "system", "anonymous"
    coordinator_id: int | None = Field(default=None, foreign_key="coordinators.id")
    donor_id: int | None = Field(default=None, foreign_key="donors.id", index=True)
    request_id: int | None = Field(default=None, foreign_key="requests.id", index=True)
    contact_attempt_id: int | None = Field(
        default=None, foreign_key="contact_attempts.id"
    )
    # Generic JSON-serializable detail blob. Must NOT contain phone numbers, names, or tokens.
    # For self-delete we record an anonymous count instead of PII (F3.5 / F11.1).
    detail: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
