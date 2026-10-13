"""Donor self-service tests (F3)."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.models.area import Area
from app.models.audit_log import AuditLog
from app.models.donor import Donor, DonorStatus


@pytest.fixture
def setup(app_client, engine):
    with Session(engine) as session:
        a1 = Area(name="Dhanmondi", is_active=True)
        a2 = Area(name="Mirpur", is_active=True)
        session.add(a1)
        session.add(a2)
        session.commit()
        session.refresh(a1)
        session.refresh(a2)
    # Register one donor
    r = app_client.get("/donor/register")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    post_r = app_client.post(
        "/donor/register",
        data={
            "name": "Alice",
            "blood_group": "A+",
            "phone": "01712345678",
            "area_id": str(a1.id),
            "is_over_18": "yes",
            "consent_contact": "yes",
            "consent_verify": "yes",
            "csrf_token": csrf,
        },
    )
    # Re-fetch the rendered page to read the manage link, in case the
    # POST returned the success page directly.
    import re
    m = re.search(r"/donor/manage/([A-Za-z0-9_-]+)", post_r.text)
    if m is None:
        raise AssertionError(
            f"manage link not found. status={post_r.status_code}, body={post_r.text!r}"
        )
    return m.group(1), a1.id, a2.id


def test_manage_link_works(app_client, engine, setup):
    token, area1, _ = setup
    r = app_client.get(f"/donor/manage/{token}")
    assert r.status_code == 200
    assert "Manage" in r.text
    assert "A+" in r.text
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
    # Phone must be masked in the rendered page.
    assert d.phone_normalized not in r.text
    assert "•••" in r.text


def test_manage_wrong_token_returns_404(app_client):
    r = app_client.get("/donor/manage/this-is-not-a-real-token")
    assert r.status_code == 404
    # No info leak: the body should not differentiate
    assert "donor" not in r.text.lower() or "not found" in r.text.lower()


def test_manage_toggle_availability(app_client, engine, setup):
    token, area1, _ = setup
    r = app_client.get(f"/donor/manage/{token}")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    # Toggle off
    r = app_client.post(
        f"/donor/manage/{token}",
        data={
            "is_available": "",  # unchecked
            "area_id": str(area1),
            "phone": "",
            "last_donation_date": "",
            "action": "update",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
    assert d.is_available is False


def test_manage_change_area(app_client, engine, setup):
    token, area1, area2 = setup
    r = app_client.get(f"/donor/manage/{token}")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = app_client.post(
        f"/donor/manage/{token}",
        data={
            "is_available": "yes",
            "area_id": str(area2),
            "phone": "",
            "last_donation_date": "",
            "action": "update",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
    assert d.area_id == area2


def test_manage_phone_change_resets_verification(app_client, engine, setup):
    token, area1, _ = setup
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
        d.status = DonorStatus.VERIFIED.value
        session.add(d)
        session.commit()
    r = app_client.get(f"/donor/manage/{token}")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = app_client.post(
        f"/donor/manage/{token}",
        data={
            "is_available": "yes",
            "area_id": str(area1),
            "phone": "01912345678",
            "last_donation_date": "",
            "action": "update",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
    assert d.status == DonorStatus.UNVERIFIED.value
    assert d.phone_normalized == "+8801912345678"


def test_manage_delete_my_data(app_client, engine, setup):
    from app.models.audit_log import AuditAction
    from app.models.contact_attempt import ContactAttempt
    from app.models.coordinator import Coordinator
    from app.security import hash_password

    token, _, _ = setup
    # Pre-seed a coordinator + contact attempt linked to this donor
    with Session(engine) as session:
        coord = Coordinator(username="c1", password_hash=hash_password("x"))
        session.add(coord)
        session.commit()
        session.refresh(coord)
        donor = session.exec(select(Donor)).first()
        session.add(
            ContactAttempt(
                donor_id=donor.id, request_id=0, coordinator_id=coord.id,
                outcome="contacted", note="hi"
            )
        )
        session.commit()
    r = app_client.get(f"/donor/manage/{token}")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = app_client.post(
        f"/donor/manage/{token}",
        data={"csrf_token": csrf, "action": "delete"},
    )
    assert r.status_code == 404
    with Session(engine) as session:
        donors = list(session.exec(select(Donor)).all())
    assert len(donors) == 0
    # Anonymous audit row remains
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(AuditLog).where(AuditLog.action == AuditAction.DONOR_SELF_DELETE.value)
            ).all()
        )
    assert len(rows) == 1
    # Old link returns 404 now
    r2 = app_client.get(f"/donor/manage/{token}")
    assert r2.status_code == 404
    # Audit log must NOT have any rows pointing at the now-deleted
    # contact_attempt via contact_attempt_id (FK would be dangling
    # otherwise; Postgres would reject the commit).
    with Session(engine) as session:
        dangling = list(
            session.exec(
                select(AuditLog).where(AuditLog.contact_attempt_id.is_not(None))
            ).all()
        )
    assert dangling == [], f"audit rows still reference deleted attempts: {dangling}"


def test_manage_regenerate_link_old_stops_working(app_client, engine, setup):
    """F3.6: coordinator can regenerate the manage link; the old one stops working.
    Implemented as part of M4 (coordinator donor management), but the manage-link
    invalidation logic is the same — we assert the precondition here using a direct
    DB write to simulate regeneration."""
    from app.tokens import hash_token, new_token

    token, _, _ = setup
    # Simulate regeneration: replace the token hash.
    new_plain = new_token(24)
    with Session(engine) as session:
        d = session.exec(select(Donor)).first()
        d.manage_token_hash = hash_token(new_plain)
        session.add(d)
        session.commit()
    # Old token is invalid
    r = app_client.get(f"/donor/manage/{token}")
    assert r.status_code == 404
    # New token works
    r2 = app_client.get(f"/donor/manage/{new_plain}")
    assert r2.status_code == 200


def test_manage_does_not_rotate_telegram_pending_code(
    app_client, engine, setup, monkeypatch
):
    """The 15-minute TTL on the Telegram link code must NOT slide on every
    page load: if a live, unexpired code already exists, we should reuse it
    (i.e. NOT overwrite pending_code_hash). Otherwise a parallel tab clicking
    the bot would race with a new code being generated here.
    """
    from datetime import UTC, datetime, timedelta

    from app.models.telegram_link import TelegramLink
    from app.tokens import hash_token

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "testbot")
    get_settings.cache_clear()

    token, _area1, _ = setup
    # Find the donor and seed a fresh, unexpired pending code.
    with Session(engine) as session:
        donor = session.exec(select(Donor)).first()
        assert donor is not None
        donor_id = donor.id
        original_hash = hash_token("ORIGINAL-CODE-123")
        link = TelegramLink(
            donor_id=donor_id,
            pending_code_hash=original_hash,
            pending_code_expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(link)
        session.commit()

    # First page load: must NOT rotate (live code exists).
    r1 = app_client.get(f"/donor/manage/{token}")
    assert r1.status_code == 200
    with Session(engine) as session:
        link1 = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor_id)
        ).first()
        assert link1 is not None
        assert link1.pending_code_hash == original_hash  # unchanged

    # Second page load: still must NOT rotate.
    r2 = app_client.get(f"/donor/manage/{token}")
    assert r2.status_code == 200
    with Session(engine) as session:
        link2 = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor_id)
        ).first()
        assert link2.pending_code_hash == original_hash
        # expires_at should also be the original, not refreshed
        assert link2.pending_code_expires_at == link1.pending_code_expires_at
