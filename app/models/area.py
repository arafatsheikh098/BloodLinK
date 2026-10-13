"""Areas managed by coordinators (used by donors and requests)."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Area(SQLModel, table=True):
    __tablename__ = "areas"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True, max_length=120, min_length=1)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)
