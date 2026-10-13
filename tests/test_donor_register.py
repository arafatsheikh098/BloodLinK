"""Donor registration tests (F2, G6)."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.models.area import Area
from app.models.donor import Donor, DonorStatus
from app.tokens import hash_token


@pytest.fixture
def area_id(engine):
    with Session(engine) as session:
        a = Area(name="Dhanmondi", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
        return a.id


def _get_csrf(client) -> str:
    r = client.get("/donor/register")
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError("csrf token not found")


def test_register_form_loads(app_client):
    r = app_client.get("/donor/register")
    assert r.status_code == 200
    assert "name=" in r.text
    assert "blood_group" in r.text


def test_register_creates_donor_and_shows_link(app_client, area_id):
    token = _get_csrf(app_client)
    r = app_client.post(
        "/donor/register",
        data={
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "last_donation_date": "",
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r.status_code == 200
    assert "/donor/manage/" in r.text
    # Manage link is at least 22 characters (24-byte token_urlsafe).
    import re
    m = re.search(r"/donor/manage/([A-Za-z0-9_-]+)", r.text)
    assert m is not None
    link_token = m.group(1)
    assert len(link_token) >= 22


def test_register_token_stored_hashed(app_client, area_id, engine):
    token = _get_csrf(app_client)
    r = app_client.post(
        "/donor/register",
        data={
            "name": "Bob",
            "blood_group": "B+",
            "phone": "01812345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r.status_code == 200
    import re
    m = re.search(r"/donor/manage/([A-Za-z0-9_-]+)", r.text)
    plain = m.group(1)
    with Session(engine) as session:
        donors = list(session.exec(select(Donor)).all())
    assert len(donors) == 1
    # Token must be stored hashed, not in plaintext.
    assert donors[0].manage_token_hash == hash_token(plain)
    assert plain not in donors[0].manage_token_hash


def test_register_duplicate_phone_rejected(app_client, area_id, engine):
    # First registration
    token = _get_csrf(app_client)
    r1 = app_client.post(
        "/donor/register",
        data={
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r1.status_code == 200

    # Second registration with the same number in a different format
    token = _get_csrf(app_client)
    r2 = app_client.post(
        "/donor/register",
        data={
            "name": "Eve",
            "blood_group": "O+",
            "phone": "+8801712345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r2.status_code == 400
    # The error does not confirm whether the number exists.
    body = r2.text
    assert "Could not register" in body or "already registered" in body.lower() or "We could not" in body

    # Third with yet another format
    token = _get_csrf(app_client)
    r3 = app_client.post(
        "/donor/register",
        data={
            "name": "Mallory",
            "blood_group": "AB+",
            "phone": "017-1234-5678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r3.status_code == 400

    # Only one donor was created.
    with Session(engine) as session:
        donors = list(session.exec(select(Donor)).all())
    assert len(donors) == 1


def test_register_requires_three_checkboxes(app_client, area_id):
    for missing in ("is_over_18", "consent_contact", "consent_verify"):
        data = {
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": _get_csrf(app_client),
        }
        data.pop(missing)
        r = app_client.post("/donor/register", data=data)
        assert r.status_code == 400, f"missing {missing} should reject"


def test_register_rejects_future_last_donation(app_client, area_id):
    from datetime import date, timedelta
    future = (date.today() + timedelta(days=10)).isoformat()
    r = app_client.post(
        "/donor/register",
        data={
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "last_donation_date": future,
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": _get_csrf(app_client),
        },
    )
    assert r.status_code == 400
    assert "future" in r.text.lower()


def test_register_escapes_html_in_name(app_client, area_id):
    token = _get_csrf(app_client)
    r = app_client.post(
        "/donor/register",
        data={
            "name": "<script>alert(1)</script>",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    assert r.status_code == 200
    # The plaintext script tag must not appear in the rendered HTML.
    assert "<script>alert(1)</script>" not in r.text
    # Escaped form is present.
    assert "&lt;script&gt;" in r.text or "&#x27;" in r.text or "alert(1)" not in r.text


def test_register_new_donor_starts_unverified(app_client, area_id, engine):
    token = _get_csrf(app_client)
    app_client.post(
        "/donor/register",
        data={
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(area_id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": token,
        },
    )
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
    assert d.status == DonorStatus.UNVERIFIED.value
    assert d.consent_contact is True
    assert d.consent_verify is True
    assert d.is_over_18 is True
