"""Request submission attempt log (F5.3, F5.4).

We record every public request submission (including honeypot-tripped ones,
which we silently drop, and rejected ones) so we can enforce:
  - per-IP: at most 5 submissions per hour (F5.3)
  - per-phone: at most 3 ACTIVE requests (F5.4)

The IP and phone fields are indexed but not unique — we count by filter.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequestAttempt(SQLModel, table=True):
    __tablename__ = "request_attempts"

    id: int | None = Field(default=None, primary_key=True)
    source_ip: str | None = Field(default=None, max_length=64, index=True)
    # SHA-256 hex of the normalized requester phone. We never store the
    # plaintext here — we only need to count.
    requester_phone_hash: str | None = Field(
        default=None, max_length=128, index=True
    )
    # True if the submission was accepted (i.e. a request was created). False
    # for honeypot, validation failure, or rate-limited attempts that we still
    # recorded for forensics.
    accepted: bool = Field(default=False)
    # Optional link to the created request (NULL when dropped or failed).
    request_id: int | None = Field(default=None, foreign_key="requests.id")
    created_at: datetime = Field(default_factory=_utcnow, index=True)
