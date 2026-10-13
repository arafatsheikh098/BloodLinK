"""Request form validation and helpers (F5 / F6).

Centralises the rules that govern a BloodRequest so route code stays thin.
Validation is intentionally strict and surfaces every problem at once so the
user does not have to play whack-a-mole with errors.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

from app.models.donor import BLOOD_GROUPS
from app.phone import PhoneNormalizationError, normalize_bd_mobile

# F5.1: units 1-10
UNITS_MIN: Final = 1
UNITS_MAX: Final = 10
# F5.1: needed_by within 14 days
NEEDED_BY_MAX_DAYS: Final = 14
# F5.1: note max length
NOTE_MAX_LENGTH: Final = 200
# F5.1: hospital name max length
HOSPITAL_NAME_MAX_LENGTH: Final = 200
# F5.1: requester name max length
REQUESTER_NAME_MAX_LENGTH: Final = 120
# Honeypot field (F5.2). A real user never fills this in.
HONEYPOT_FIELD: Final = "website"


class RequestValidationError(ValueError):
    """Raised when a request form value is invalid.

    `field` is the form field name (used to surface inline errors);
    `message` is human-readable.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


def validate_request_form(
    *,
    blood_group: str | None,
    units_raw: str | None,
    hospital_name: str | None,
    area_id_raw: str | None,
    needed_by_raw: str | None,
    requester_name: str | None,
    requester_phone: str | None,
    note: str | None,
    honeypot: str | None,
    consent_contact: str | None,
    now: datetime | None = None,
) -> dict[str, str | int | datetime]:
    """Return a dict of cleaned values or raise RequestValidationError.

    The first error wins (so callers can display one inline message at a time),
    matching the donor registration flow.
    """
    now = now or datetime.now(UTC)

    # F5.2: honeypot. We do NOT raise; we signal silent drop instead.
    if honeypot:
        raise HoneypotTripped()

    if not blood_group or blood_group not in BLOOD_GROUPS:
        raise RequestValidationError("blood_group", "Please choose a valid blood group.")

    try:
        units = int(units_raw or "")
    except ValueError as exc:
        raise RequestValidationError("units", "Units must be a number between 1 and 10.") from exc
    if not (UNITS_MIN <= units <= UNITS_MAX):
        raise RequestValidationError("units", "Units must be between 1 and 10.")

    hospital_name = (hospital_name or "").strip()
    if not (1 <= len(hospital_name) <= HOSPITAL_NAME_MAX_LENGTH):
        raise RequestValidationError("hospital_name", "Please enter the hospital name.")

    try:
        area_id = int(area_id_raw or "")
    except ValueError as exc:
        raise RequestValidationError("area_id", "Please choose a valid area.") from exc

    # F5.1: needed_by in the future AND within 14 days
    try:
        needed_by = datetime.fromisoformat(needed_by_raw or "")
    except ValueError as exc:
        raise RequestValidationError("needed_by", "Please enter a valid date and time.") from exc
    if needed_by.tzinfo is None:
        # Treat naive as local — we compare in UTC.
        needed_by = needed_by.replace(tzinfo=UTC)
    if needed_by <= now:
        raise RequestValidationError("needed_by", "Needed-by time must be in the future.")
    if needed_by > now + timedelta(days=NEEDED_BY_MAX_DAYS):
        raise RequestValidationError(
            "needed_by", f"Needed-by time must be within {NEEDED_BY_MAX_DAYS} days."
        )

    requester_name = (requester_name or "").strip()
    if not (1 <= len(requester_name) <= REQUESTER_NAME_MAX_LENGTH):
        raise RequestValidationError("requester_name", "Please enter your name.")

    try:
        normalized_phone = normalize_bd_mobile(requester_phone or "")
    except PhoneNormalizationError as exc:
        raise RequestValidationError("requester_phone", str(exc)) from exc

    note = (note or "").strip()
    if len(note) > NOTE_MAX_LENGTH:
        raise RequestValidationError("note", f"Note must be at most {NOTE_MAX_LENGTH} characters.")

    if not consent_contact:
        raise RequestValidationError("consent_contact", "Please confirm consent to be contacted.")

    return {
        "blood_group": blood_group,
        "units": units,
        "hospital_name": hospital_name,
        "area_id": area_id,
        "needed_by": needed_by,
        "requester_name": requester_name,
        "requester_phone": normalized_phone,
        "note": note or None,
        "consent_contact": bool(consent_contact),
    }


class HoneypotTripped(Exception):
    """Raised when a honeypot field has been filled in (F5.2).

    The route handler should respond with 200 + the success page WITHOUT
    creating a request, so the bot does not know it was caught.
    """


def effective_status(
    stored_status: str, needed_by: datetime, now: datetime | None = None
) -> str:
    """Return the effective status, applying F6.5 (compute expiry on read).

    If the stored status is already terminal (fulfilled/cancelled/rejected)
    we keep it. Otherwise if needed_by has passed, we return "expired".
    """
    from app.models.request import RequestStatus

    now = now or datetime.now(UTC)
    if needed_by.tzinfo is None:
        needed_by = needed_by.replace(tzinfo=UTC)
    if stored_status in {
        RequestStatus.FULFILLED.value,
        RequestStatus.CANCELLED.value,
        RequestStatus.REJECTED.value,
    }:
        return stored_status
    if needed_by < now:
        return RequestStatus.EXPIRED.value
    return stored_status
