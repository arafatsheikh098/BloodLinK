"""Public blood request form tests (F5).

Covers F5.1 validation, F5.2 honeypot, F5.3 IP rate limit, F5.4 phone active
limit, F5.5 tracking link, F5.6 random token URL.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlmodel import Session, select

from app.models.area import Area
from app.models.request import BloodRequest, RequestStatus
from app.models.request_attempt import RequestAttempt


@pytest.fixture
def area_id(engine):
    with Session(engine) as session:
        a = Area(name="Dhanmondi", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
        return a.id


def _get_csrf(client) -> str:
    r = client.get("/request/new")
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError("csrf token not found")


def _future_iso(hours: int = 6) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).replace(microsecond=0).isoformat()


def _post_valid(client, area_id, **overrides):
    data = dict(
        blood_group="A+",
        units="2",
        hospital_name="Square Hospital",
        area_id=str(area_id),
        needed_by=_future_iso(),
        requester_name="Rita",
        requester_phone="01712345678",
        note="Urgent",
        consent_contact="yes",
        website="",
        csrf_token=_get_csrf(client),
    )
    data.update(overrides)
    return client.post("/request/new", data=data)


# --- F5.1 validation --------------------------------------------------------


def test_request_form_loads(app_client):
    r = app_client.get("/request/new")
    assert r.status_code == 200
    assert "name=" in r.text
    assert "blood_group" in r.text


def test_valid_form_creates_request_and_shows_link(app_client, area_id):
    r = _post_valid(app_client, area_id)
    assert r.status_code == 200
    assert "/request/" in r.text
    # Find the tracking link (excludes the /request/new nav/form action).
    m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
    assert m is not None, f"tracking link not found: {r.text[:2000]!r}"
    token = m.group(1)
    assert len(token) >= 22


def test_invalid_units_rejected(app_client, area_id):
    r = _post_valid(app_client, area_id, units="0")
    assert r.status_code == 400


def test_invalid_needed_by_rejected(app_client, area_id):
    r = _post_valid(app_client, area_id, needed_by="not-a-date")
    assert r.status_code == 400


def test_past_needed_by_rejected(app_client, area_id):
    past = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    r = _post_valid(app_client, area_id, needed_by=past)
    assert r.status_code == 400


def test_more_than_14_days_rejected(app_client, area_id):
    far = (datetime.now(UTC) + timedelta(days=15)).replace(microsecond=0).isoformat()
    r = _post_valid(app_client, area_id, needed_by=far)
    assert r.status_code == 400


def test_overlong_note_rejected(app_client, area_id):
    r = _post_valid(app_client, area_id, note="x" * 201)
    assert r.status_code == 400


def test_invalid_phone_rejected(app_client, area_id):
    r = _post_valid(app_client, area_id, requester_phone="not-a-phone")
    assert r.status_code == 400


def test_missing_consent_rejected(app_client, area_id):
    r = _post_valid(app_client, area_id, consent_contact="")
    assert r.status_code == 400


def test_form_works_without_javascript(app_client):
    """F5.5: form must work without JS."""
    r = app_client.get("/request/new")
    # No <script> with required client logic — we just check the form posts
    # to /request/new (action attr is present).
    assert 'action="/request/new"' in r.text
    # No inline JS disabling or required scripts
    assert "disabled" not in r.text.lower()


# --- F5.2 honeypot -----------------------------------------------------------


def test_honeypot_filled_is_silently_dropped(app_client, area_id):
    r = _post_valid(app_client, area_id, website="http://spam.example.com")
    # Render the success page (no error, no token) so the bot doesn't notice
    assert r.status_code == 200
    # No request should be created.
    from sqlmodel import Session, select

    from app.db import get_engine

    with Session(get_engine()) as session:
        rows = list(session.exec(select(BloodRequest)).all())
    assert len(rows) == 0
    # A RequestAttempt row is recorded (accepted=False).
    with Session(get_engine()) as session:
        attempts = list(session.exec(select(RequestAttempt)).all())
    assert len(attempts) == 1
    assert attempts[0].accepted is False


# --- F5.3 IP rate limit ------------------------------------------------------


def test_ip_rate_limit_6th_returns_429(app_client, area_id):
    """F5.3: the 6th submission from one IP within an hour is rejected with 429."""
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base):
        for i in range(5):
            r = _post_valid(
                app_client,
                area_id,
                requester_phone=f"01712345{600 + i:03d}",  # unique phones so the per-phone limit doesn't trip
            )
            # We accept 200 (success) or 400 (e.g. phone dup with active cap not yet hit)
            assert r.status_code in {200, 400}, f"attempt {i+1} status={r.status_code}"
        # 6th attempt → 429
        r = _post_valid(
            app_client,
            area_id,
            requester_phone="01712345700",
        )
        assert r.status_code == 429


# --- F5.4 phone active cap ---------------------------------------------------


def test_phone_active_cap(app_client, area_id):
    """F5.4: 4th active request from same phone is rejected."""
    # Create 3 pending requests directly via DB.
    from sqlmodel import Session

    from app.db import get_engine
    from app.phone import normalize_bd_mobile
    from app.tokens import new_token

    phone = "01712345678"
    with Session(get_engine()) as session:
        for _ in range(3):
            req = BloodRequest(
                public_token=new_token(24),
                blood_group="A+",
                units=1,
                hospital_name="H",
                area_id=area_id,
                needed_by=datetime.now(UTC) + timedelta(hours=2),
                requester_name="X",
                requester_phone_normalized=normalize_bd_mobile(phone),
                status=RequestStatus.PENDING.value,
            )
            session.add(req)
        session.commit()

    # Submitting a 4th from the same phone → 400 (phone_too_many in template error key)
    r = _post_valid(app_client, area_id, requester_phone=phone)
    assert r.status_code == 400


# --- F5.5 / F5.6 tracking link & random token -------------------------------


def test_tracking_link_works(app_client, area_id, engine):
    r = _post_valid(app_client, area_id)
    m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
    assert m is not None
    token = m.group(1)
    r2 = app_client.get(f"/request/{token}")
    assert r2.status_code == 200
    assert "A+" in r2.text
    assert "Square Hospital" in r2.text
    # The render must NOT include the requester phone (F6.4).
    assert "+8801712345678" not in r2.text
    assert "01712345678" not in r2.text


def test_tracking_wrong_token_renders_not_found(app_client):
    r = app_client.get("/request/this-is-not-a-real-token")
    assert r.status_code == 200
    assert "not found" in r.text.lower() or "could not" in r.text.lower()


def test_public_url_does_not_use_sequential_ids(app_client, area_id):
    """F5.6: the tracking URL must not contain an integer id."""
    r = _post_valid(app_client, area_id)
    m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
    token = m.group(1)
    # Token is not a pure integer — it must contain at least one non-digit.
    assert not token.isdigit()
    assert len(token) >= 22


def test_tracking_token_unique(app_client, area_id, engine):
    seen = set()
    for _ in range(3):
        r = _post_valid(app_client, area_id)
        m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
        seen.add(m.group(1))
    assert len(seen) == 3


# --- requester cancellation (F6.4) -------------------------------------------


def test_requester_can_cancel_pending_request(app_client, area_id):
    r = _post_valid(app_client, area_id)
    m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
    token = m.group(1)
    # Get tracking page so a fresh CSRF token is available
    r2 = app_client.get(f"/request/{token}")
    assert r2.status_code == 200
    csrf = None
    for line in r2.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    assert csrf
    r3 = app_client.post(f"/request/{token}", data={"csrf_token": csrf})
    assert r3.status_code == 303
    # Re-fetch the underlying request to confirm cancellation
    from sqlmodel import Session

    from app.db import get_engine

    with Session(get_engine()) as session:
        req = session.exec(select(BloodRequest).where(BloodRequest.public_token == token)).first()
    assert req.status == RequestStatus.CANCELLED.value


def test_cannot_cancel_after_fulfilled(app_client, area_id, engine):
    r = _post_valid(app_client, area_id)
    m = re.search(r'href="/request/([A-Za-z0-9_-]{22,})"', r.text)
    token = m.group(1)
    # Mark fulfilled directly in DB
    from sqlmodel import Session

    from app.db import get_engine

    with Session(get_engine()) as session:
        req = session.exec(select(BloodRequest).where(BloodRequest.public_token == token)).first()
        req.status = RequestStatus.FULFILLED.value
        session.add(req)
        session.commit()
    # Get CSRF
    r2 = app_client.get(f"/request/{token}")
    csrf = None
    for line in r2.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r3 = app_client.post(f"/request/{token}", data={"csrf_token": csrf})
    # 303 redirect; the underlying status was already terminal
    assert r3.status_code == 303
    with Session(get_engine()) as session:
        req = session.exec(select(BloodRequest).where(BloodRequest.public_token == token)).first()
    assert req.status == RequestStatus.FULFILLED.value
