"""Blood request model (F5, F6)."""
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RequestStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"  # computed; not stored as canonical status, but allowed for persistence


# Effective statuses that count as "open" for phone-rate-limit purposes.
ACTIVE_STATUSES = (
    RequestStatus.PENDING.value,
    RequestStatus.VERIFIED.value,
)


class BloodRequest(SQLModel, table=True):
    __tablename__ = "requests"

    id: int | None = Field(default=None, primary_key=True)
    # SHA-256 hash of the random public token used in tracking URLs. We
    # store the hash, not the plaintext, so a DB read does not reveal
    # any active tracking URL (F11.1: secrets must be hashed at rest).
    public_token_hash: str = Field(
        index=True, unique=True, max_length=128
    )

    blood_group: str = Field(index=True, max_length=4, min_length=2)
    units: int = Field(ge=1, le=10)
    hospital_name: str = Field(max_length=200, min_length=1)
    area_id: int = Field(foreign_key="areas.id", index=True)
    needed_by: datetime = Field(index=True)

    requester_name: str = Field(max_length=120, min_length=1)
    requester_phone_normalized: str = Field(index=True, max_length=20)
    note: str | None = Field(default=None, max_length=200)
    consent_contact: bool = Field(default=False)

    status: str = Field(default=RequestStatus.PENDING.value, index=True, max_length=16)
    reject_reason: str | None = Field(default=None, max_length=500)
    verified_by_id: int | None = Field(default=None, foreign_key="coordinators.id")
    verified_at: datetime | None = Field(default=None)
    closed_at: datetime | None = Field(default=None)

    # Source IP for rate limiting (per-IP, per-hour). Not PII; stored as text.
    source_ip: str | None = Field(default=None, max_length=64, index=True)

    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
