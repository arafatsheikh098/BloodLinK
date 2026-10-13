"""Per-coordinator login attempt log (F1.3)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class LoginAttempt(SQLModel, table=True):
    __tablename__ = "login_attempts"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, max_length=64)
    # Hash of the username (so we don't store the raw identifier in plain form
    # in this table; we only need it to count failures per username).
    username_hash: str = Field(index=True, max_length=128)
    # NULL on unknown username (so we never confirm or deny existence).
    coordinator_id: int | None = Field(default=None, foreign_key="coordinators.id", index=True)
    success: bool = Field(default=False)
    source_ip: str | None = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
