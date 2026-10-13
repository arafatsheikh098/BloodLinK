"""End-to-end public pages test (F9.1)."""
from __future__ import annotations

from sqlmodel import Session

from app.models.area import Area
from app.models.donor import Donor, DonorStatus
from app.phone import normalize_bd_mobile
from app.tokens import hash_token, new_token


def test_home_loads_and_has_no_pii(app_client):
    r = app_client.get("/")
    assert r.status_code == 200
    assert "+880" not in r.text
    body = r.text.lower()
    assert "blood" in body or "donor" in body or "request" in body


def test_privacy_loads(app_client):
    r = app_client.get("/privacy")
    assert r.status_code == 200
    body = r.text.lower()
    assert "privacy" in body
    assert "collect" in body or "what" in body


def test_stats_loads(app_client):
    r = app_client.get("/stats")
    assert r.status_code == 200
    body = r.text.lower()
    assert "donor" in body or "verified" in body or "fewer" in body


def test_home_does_not_contain_donor_data(app_client, engine):
    with Session(engine) as session:
        a = Area(name="X", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
        d = Donor(
            manage_token_hash=hash_token(new_token(24)),
            name="SecretName",
            blood_group="A+",
            phone_normalized=normalize_bd_mobile("01712345699"),
            area_id=a.id,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
            status=DonorStatus.VERIFIED.value,
        )
        session.add(d)
        session.commit()
    r = app_client.get("/")
    assert r.status_code == 200
    assert "SecretName" not in r.text
    assert "01712345699" not in r.text
