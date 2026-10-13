"""Contact attempt log per donor per request (F7)."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ContactOutcome(str, Enum):
    CONTACTED = "contacted"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    NO_ANSWER = "no_answer"
    DONATED = "donated"


class ContactAttempt(SQLModel, table=True):
    __tablename__ = "contact_attempts"

    id: int | None = Field(default=None, primary_key=True)
    donor_id: int = Field(foreign_key="donors.id", index=True)
    request_id: int = Field(foreign_key="requests.id", index=True)
    coordinator_id: int = Field(foreign_key="coordinators.id")
    outcome: str = Field(max_length=16, index=True)
    note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_utcnow)
