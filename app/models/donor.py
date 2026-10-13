"""Donor model (F2, F3, F4)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


BLOOD_GROUPS = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


class DonorStatus(str, Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    SUSPENDED = "suspended"


class Donor(SQLModel, table=True):
    __tablename__ = "donors"

    id: int | None = Field(default=None, primary_key=True)
    # Public token used in manage links; manage tokens are stored hashed separately.
    manage_token_hash: str | None = Field(
        default=None, index=True, unique=True, max_length=128
    )
    name: str = Field(max_length=120, min_length=1)
    blood_group: str = Field(index=True, max_length=4, min_length=2)
    phone_normalized: str = Field(index=True, unique=True, max_length=20)
    area_id: int = Field(foreign_key="areas.id", index=True)
    last_donation_date: date | None = Field(default=None)
    is_available: bool = Field(default=True)
    status: str = Field(default=DonorStatus.UNVERIFIED.value, index=True, max_length=16)
    is_over_18: bool = Field(default=False)
    consent_contact: bool = Field(default=False)
    consent_verify: bool = Field(default=False)
    verify_note: str | None = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
