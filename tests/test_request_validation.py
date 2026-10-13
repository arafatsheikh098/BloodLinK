"""Request validation and rate limit helpers (F5.1, F5.3, F5.4)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.request_validation import (
    HONEYPOT_FIELD,
    HoneypotTripped,
    RequestValidationError,
    effective_status,
    validate_request_form,
)


def _valid_kwargs(**overrides):
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    needed_by = (now + timedelta(hours=6)).replace(microsecond=0).isoformat()
    base = dict(
        blood_group="A+",
        units_raw="2",
        hospital_name="Square Hospital",
        area_id_raw="1",
        needed_by_raw=needed_by,
        requester_name="Rita",
        requester_phone="01712345678",
        note="Urgent",
        honeypot="",
        consent_contact="yes",
        now=now,
    )
    base.update(overrides)
    return base


def test_validation_passes_for_complete_input():
    cleaned = validate_request_form(**_valid_kwargs())
    assert cleaned["blood_group"] == "A+"
    assert cleaned["units"] == 2
    assert cleaned["hospital_name"] == "Square Hospital"
    assert cleaned["area_id"] == 1
    assert cleaned["requester_name"] == "Rita"
    assert cleaned["requester_phone"] == "+8801712345678"
    assert cleaned["note"] == "Urgent"
    assert cleaned["consent_contact"] is True


def test_validation_rejects_invalid_blood_group():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(blood_group="ZZ"))
    assert exc.value.field == "blood_group"


def test_validation_rejects_units_too_high():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(units_raw="11"))
    assert exc.value.field == "units"


def test_validation_rejects_units_too_low():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(units_raw="0"))
    assert exc.value.field == "units"


def test_validation_rejects_non_integer_units():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(units_raw="abc"))
    assert exc.value.field == "units"


def test_validation_rejects_past_needed_by():
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    past = (now - timedelta(hours=1)).replace(microsecond=0).isoformat()
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(needed_by_raw=past))
    assert exc.value.field == "needed_by"


def test_validation_rejects_more_than_14_days():
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    future = (now + timedelta(days=15)).replace(microsecond=0).isoformat()
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(needed_by_raw=future))
    assert exc.value.field == "needed_by"


def test_validation_rejects_overlong_note():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(note="x" * 201))
    assert exc.value.field == "note"


def test_validation_normalizes_phone():
    cleaned = validate_request_form(**_valid_kwargs(requester_phone="+8801712345678"))
    assert cleaned["requester_phone"] == "+8801712345678"


def test_validation_rejects_bad_phone():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(requester_phone="not-a-phone"))
    assert exc.value.field == "requester_phone"


def test_validation_rejects_missing_consent():
    with pytest.raises(RequestValidationError) as exc:
        validate_request_form(**_valid_kwargs(consent_contact=""))
    assert exc.value.field == "consent_contact"


def test_honeypot_tripped():
    with pytest.raises(HoneypotTripped):
        validate_request_form(**_valid_kwargs(honeypot="http://spam.example.com"))


def test_honeypot_field_name_constant():
    assert HONEYPOT_FIELD == "website"


def test_effective_status_marks_expired():
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    past = now - timedelta(hours=1)
    assert effective_status("pending", past, now=now) == "expired"
    assert effective_status("verified", past, now=now) == "expired"


def test_effective_status_keeps_terminal_states():
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    past = now - timedelta(hours=1)
    assert effective_status("fulfilled", past, now=now) == "fulfilled"
    assert effective_status("cancelled", past, now=now) == "cancelled"
    assert effective_status("rejected", past, now=now) == "rejected"


def test_effective_status_keeps_open_when_in_future():
    now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=UTC)
    future = now + timedelta(hours=6)
    assert effective_status("pending", future, now=now) == "pending"
    assert effective_status("verified", future, now=now) == "verified"
