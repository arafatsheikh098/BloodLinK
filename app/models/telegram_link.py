"""Telegram linking one-time codes and stored chat ids (F8)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TelegramLink(SQLModel, table=True):
    __tablename__ = "telegram_links"

    id: int | None = Field(default=None, primary_key=True)
    donor_id: int = Field(foreign_key="donors.id", index=True, unique=True)
    # Stored only after a successful link. Until then chat_id is NULL.
    chat_id: str | None = Field(default=None, max_length=64, index=True)
    # Pending one-time code (hashed) and expiry.
    pending_code_hash: str | None = Field(default=None, max_length=128)
    pending_code_expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
