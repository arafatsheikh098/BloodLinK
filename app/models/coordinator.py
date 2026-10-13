"""Coordinator account (F1)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Coordinator(SQLModel, table=True):
    __tablename__ = "coordinators"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=64, min_length=1)
    password_hash: str = Field(max_length=512)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
