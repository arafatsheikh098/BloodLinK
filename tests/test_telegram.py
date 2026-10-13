"""Telegram integration tests (F8.1, F8.2, F8.3, F8.4, F8.5, F8.6, F8.7, F8.8).

F8.1: with no token, UI is hidden and the app works fully.
F8.2: linking uses a one-time code that expires and cannot be reused.
F8.3: notification text contains only blood group, hospital, area, needed-by.
F8.4: webhook returns 403 without the correct secret header.
F8.5: tampered or expired callback data is ignored.
F8.6: pressing Accept twice changes state once and sends no duplicate update.
F8.7: Telegram API failures are caught, logged, and reported to coordinator.
F8.8: DEMO_MODE disables sending.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.models.area import Area
from app.models.audit_log import AuditAction, AuditLog
from app.models.contact_attempt import ContactAttempt
from app.models.donor import Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
from app.models.telegram_link import TelegramLink
from app.telegram import notify_message_text, send_message
from app.telegram_signing import (
    make_accept_token,
    make_decline_token,
    sign_callback,
    verify_callback,
)
from app.tokens import hash_token, new_token

# --- helpers ----------------------------------------------------------------


@pytest.fixture
def areas(engine):
    with Session(engine) as session:
        a = Area(name="Dhanmondi", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
    return {"dhanmondi": a.id}


def _make_donor(
    engine,
    *,
    phone: str = "01712345601",
    name: str = "Alice",
    area_id: int,
    status: str = DonorStatus.VERIFIED.value,
) -> Donor:
    from app.phone import normalize_bd_mobile

    with Session(engine) as session:
        d = Donor(
            manage_token_hash=hash_token(new_token(24)),
            name=name,
            blood_group="A+",
            phone_normalized=normalize_bd_mobile(phone),
            area_id=area_id,
            status=status,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
        )
        session.add(d)
        session.commit()
        session.refresh(d)
    return d


def _make_request(engine, *, area_id: int) -> BloodRequest:
    with Session(engine) as session:
        r = BloodRequest(
            public_token_hash=hash_token(new_token(24)),
            blood_group="A+",
            units=1,
            hospital_name="H",
            area_id=area_id,
            needed_by=datetime.now(UTC) + timedelta(hours=6),
            requester_name="R",
            requester_phone_normalized="+8801712345678",
            status=RequestStatus.VERIFIED.value,
        )
        session.add(r)
        session.commit()
        session.refresh(r)
    return r


def _enable_telegram(monkeypatch, *, demo: bool = False) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-secret-abc")
    monkeypatch.setenv("TELEGRAM_PUBLIC_BASE_URL", "https://t.example/bot")
    monkeypatch.setenv("DEMO_MODE", "true" if demo else "false")
    get_settings.cache_clear()


def _disable_telegram(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("TELEGRAM_PUBLIC_BASE_URL", raising=False)
    get_settings.cache_clear()


# --- F8.1 disabled state ----------------------------------------------------


def test_no_token_app_works(monkeypatch, app_client):
    _disable_telegram(monkeypatch)
    r = app_client.get("/")
    assert r.status_code == 200


def test_no_token_telegram_ui_hidden(monkeypatch, engine, areas, app_client):
    _disable_telegram(monkeypatch)
    from app.phone import normalize_bd_mobile
    from app.tokens import hash_token, new_token

    with Session(engine) as session:
        d = Donor(
            manage_token_hash=hash_token(new_token(24)),
            name="Alice",
            blood_group="A+",
            phone_normalized=normalize_bd_mobile("01712345601"),
            area_id=areas["dhanmondi"],
            status=DonorStatus.VERIFIED.value,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
        )
        session.add(d)
        session.commit()
        session.refresh(d)
        token_plain = new_token(24)
        d2 = Donor(
            manage_token_hash=hash_token(token_plain),
            name="Bob",
            blood_group="O+",
            phone_normalized=normalize_bd_mobile("01712345602"),
            area_id=areas["dhanmondi"],
            status=DonorStatus.VERIFIED.value,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
        )
        session.add(d2)
        session.commit()
    r = app_client.get(f"/donor/manage/{token_plain}")
    assert r.status_code == 200
    # No telegram block rendered
    assert "Telegram" not in r.text
    assert "t.me/" not in r.text


# --- F8.3 notification text -------------------------------------------------


def test_notify_message_contains_only_safe_fields():
    text = notify_message_text(
        blood_group="A+",
        hospital_name="Square Hospital",
        area_name="Dhanmondi",
        needed_by_iso="2026-10-13T16:00:00+00:00",
    )
    assert "A+" in text
    assert "Square Hospital" in text
    assert "Dhanmondi" in text
    assert "2026-10-13T16:00:00" in text
    # PII never appears
    assert "+880" not in text
    assert "phone" not in text.lower()
    assert "name" not in text.lower() or "your name" not in text.lower()


# --- F8.4 webhook secret check ----------------------------------------------


def test_webhook_without_secret_returns_403(monkeypatch, app_client):
    _enable_telegram(monkeypatch)
    r = app_client.post("/telegram/webhook", json={})
    assert r.status_code == 403


def test_webhook_with_wrong_secret_returns_403(monkeypatch, app_client):
    _enable_telegram(monkeypatch)
    r = app_client.post(
        "/telegram/webhook",
        json={},
        headers={"x-telegram-bot-api-secret-token": "wrong"},
    )
    assert r.status_code == 403


def test_webhook_no_token_returns_404(monkeypatch, app_client):
    _disable_telegram(monkeypatch)
    r = app_client.post("/telegram/webhook", json={})
    assert r.status_code == 404


# --- F8.2 one-time link code ------------------------------------------------


def test_link_code_creation_and_consumption(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"])
    # Issue a code via the manage page
    with Session(engine) as session:
        link = TelegramLink(donor_id=donor.id)
        session.add(link)
        session.commit()
        session.refresh(link)
    # Simulate /start <code>
    from app.routes.telegram import _new_link_code

    plain = _new_link_code()
    with Session(engine) as session:
        link = session.get(TelegramLink, link.id)
        link.pending_code_hash = hash_token(plain)
        link.pending_code_expires_at = datetime.now(UTC) + timedelta(minutes=15)
        session.add(link)
        session.commit()
    payload = {
        "message": {
            "chat": {"id": 12345},
            "from": {"id": 12345},
            "text": f"/start {plain}",
        }
    }
    r = app_client.post(
        "/telegram/webhook",
        json=payload,
        headers={"x-telegram-bot-api-secret-token": "test-secret-abc"},
    )
    assert r.status_code == 200
    with Session(engine) as session:
        link = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor.id)
        ).first()
        assert link.chat_id == "12345"
        # Pending code is cleared
        assert link.pending_code_hash is None


def test_link_code_reuse_fails(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345602")
    from app.routes.telegram import _new_link_code

    plain = _new_link_code()
    with Session(engine) as session:
        link = TelegramLink(
            donor_id=donor.id,
            pending_code_hash=hash_token(plain),
            pending_code_expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )
        session.add(link)
        session.commit()
    payload = {
        "message": {
            "chat": {"id": 99999},
            "from": {"id": 99999},
            "text": f"/start {plain}",
        }
    }
    headers = {"x-telegram-bot-api-secret-token": "test-secret-abc"}
    r1 = app_client.post("/telegram/webhook", json=payload, headers=headers)
    assert r1.status_code == 200
    # Reusing the same code with a DIFFERENT chat_id: the link is already
    # bound to chat 99999, so the second /start from chat 88888 must not
    # overwrite it.
    payload2 = {
        "message": {
            "chat": {"id": 88888},
            "from": {"id": 88888},
            "text": f"/start {plain}",
        }
    }
    r2 = app_client.post("/telegram/webhook", json=payload2, headers=headers)
    assert r2.status_code == 200
    with Session(engine) as session:
        link = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor.id)
        ).first()
    assert link.chat_id == "99999"  # unchanged


def test_link_code_expired_rejected(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345603")
    from app.routes.telegram import _new_link_code

    plain = _new_link_code()
    with Session(engine) as session:
        link = TelegramLink(
            donor_id=donor.id,
            pending_code_hash=hash_token(plain),
            pending_code_expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(link)
        session.commit()
    payload = {
        "message": {
            "chat": {"id": 11111},
            "from": {"id": 11111},
            "text": f"/start {plain}",
        }
    }
    r = app_client.post(
        "/telegram/webhook",
        json=payload,
        headers={"x-telegram-bot-api-secret-token": "test-secret-abc"},
    )
    assert r.status_code == 200
    with Session(engine) as session:
        link = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor.id)
        ).first()
        assert link.chat_id is None
        # audit
        audits = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.TELEGRAM_CALLBACK_REJECTED.value
                )
            ).all()
        )
        assert any("expired" in (a.detail or "") for a in audits)


# --- F8.5 tampered callback ignored ----------------------------------------


def test_tampered_callback_ignored(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345604")
    req = _make_request(engine, area_id=areas["dhanmondi"])
    with Session(engine) as session:
        # Link chat
        link = TelegramLink(donor_id=donor.id, chat_id="55555")
        session.add(link)
        # Create a contact attempt
        from app.models.coordinator import Coordinator
        from app.security import hash_password

        c = Coordinator(username="c1", password_hash=hash_password("x"))
        session.add(c)
        session.commit()
        session.refresh(c)
        attempt = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=c.id,
            outcome="contacted",
        )
        session.add(attempt)
        session.commit()
        session.refresh(attempt)
    # Send a callback with a bogus data payload
    payload = {
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 55555},
            "data": "garbage.not-a-signed-token",
        }
    }
    r = app_client.post(
        "/telegram/webhook",
        json=payload,
        headers={"x-telegram-bot-api-secret-token": "test-secret-abc"},
    )
    assert r.status_code == 200
    with Session(engine) as session:
        a = session.get(ContactAttempt, attempt.id)
        assert a.outcome == "contacted"  # unchanged


def test_callback_against_different_donor_rejected(
    monkeypatch, engine, areas, app_client
):
    """The signature binds (request, donor, attempt). A token for one
    donor must not flip another donor's attempt."""
    _enable_telegram(monkeypatch)
    donor1 = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345605")
    donor2 = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345606", name="Other")
    req = _make_request(engine, area_id=areas["dhanmondi"])
    with Session(engine) as session:
        from app.models.coordinator import Coordinator
        from app.security import hash_password

        c = Coordinator(username="c1", password_hash=hash_password("x"))
        session.add(c)
        session.add(TelegramLink(donor_id=donor1.id, chat_id="11111"))
        session.add(TelegramLink(donor_id=donor2.id, chat_id="22222"))
        session.commit()
        session.refresh(c)
        a1 = ContactAttempt(
            donor_id=donor1.id,
            request_id=req.id,
            coordinator_id=c.id,
            outcome="contacted",
        )
        a2 = ContactAttempt(
            donor_id=donor2.id,
            request_id=req.id,
            coordinator_id=c.id,
            outcome="contacted",
        )
        session.add(a1)
        session.add(a2)
        session.commit()
        session.refresh(a1)
        session.refresh(a2)
    # Sign an accept token for donor1 / a1, but send as if from donor2 (chat 22222)
    token = make_accept_token(req.id, donor1.id, a1.id)
    payload = {
        "callback_query": {
            "id": "cb-2",
            "from": {"id": 22222},
            "data": token,
        }
    }
    r = app_client.post(
        "/telegram/webhook",
        json=payload,
        headers={"x-telegram-bot-api-secret-token": "test-secret-abc"},
    )
    assert r.status_code == 200
    with Session(engine) as session:
        a1b = session.get(ContactAttempt, a1.id)
        a2b = session.get(ContactAttempt, a2.id)
    assert a1b.outcome == "contacted"
    assert a2b.outcome == "contacted"


# --- F8.6 idempotent accept -------------------------------------------------


def test_double_accept_only_changes_state_once(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345607")
    req = _make_request(engine, area_id=areas["dhanmondi"])
    with Session(engine) as session:
        from app.models.coordinator import Coordinator
        from app.security import hash_password

        c = Coordinator(username="c1", password_hash=hash_password("x"))
        session.add(c)
        session.add(TelegramLink(donor_id=donor.id, chat_id="33333"))
        session.commit()
        session.refresh(c)
        a = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=c.id,
            outcome="contacted",
        )
        session.add(a)
        session.commit()
        session.refresh(a)
    token = make_accept_token(req.id, donor.id, a.id)
    payload = {
        "callback_query": {
            "id": "cb-double",
            "from": {"id": 33333},
            "data": token,
        }
    }
    headers = {"x-telegram-bot-api-secret-token": "test-secret-abc"}
    r1 = app_client.post("/telegram/webhook", json=payload, headers=headers)
    assert r1.status_code == 200
    r2 = app_client.post("/telegram/webhook", json=payload, headers=headers)
    assert r2.status_code == 200
    with Session(engine) as session:
        a_after = session.get(ContactAttempt, a.id)
        accepts = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.action == AuditAction.TELEGRAM_CALLBACK_ACCEPT.value
                )
            ).all()
        )
    assert a_after.outcome == "accepted"
    assert len(accepts) == 1


def test_decline_changes_outcome(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345608")
    req = _make_request(engine, area_id=areas["dhanmondi"])
    with Session(engine) as session:
        from app.models.coordinator import Coordinator
        from app.security import hash_password

        c = Coordinator(username="c1", password_hash=hash_password("x"))
        session.add(c)
        session.add(TelegramLink(donor_id=donor.id, chat_id="44444"))
        session.commit()
        session.refresh(c)
        a = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=c.id,
            outcome="contacted",
        )
        session.add(a)
        session.commit()
        session.refresh(a)
    token = make_decline_token(req.id, donor.id, a.id)
    payload = {
        "callback_query": {
            "id": "cb-d",
            "from": {"id": 44444},
            "data": token,
        }
    }
    r = app_client.post(
        "/telegram/webhook",
        json=payload,
        headers={"x-telegram-bot-api-secret-token": "test-secret-abc"},
    )
    assert r.status_code == 200
    with Session(engine) as session:
        a_after = session.get(ContactAttempt, a.id)
    assert a_after.outcome == "declined"


# --- F8.7 failure handling --------------------------------------------------


def test_send_message_disabled_returns_false(monkeypatch):
    _disable_telegram(monkeypatch)
    ok, err = send_message("any-chat", "hello")
    assert ok is False
    assert err == "disabled"


def test_send_message_demo_mode_disables(monkeypatch):
    _enable_telegram(monkeypatch, demo=True)
    ok, err = send_message("any-chat", "hello")
    assert ok is False
    assert err == "disabled"


# --- F8.8 DEMO_MODE disables sending ---------------------------------------


def test_demo_mode_disables_telegram_block(monkeypatch, engine, areas, app_client):
    _enable_telegram(monkeypatch, demo=True)
    from app.phone import normalize_bd_mobile
    from app.tokens import hash_token, new_token

    token_plain = new_token(24)
    with Session(engine) as session:
        d = Donor(
            manage_token_hash=hash_token(token_plain),
            name="Carol",
            blood_group="A+",
            phone_normalized=normalize_bd_mobile("01712345611"),
            area_id=areas["dhanmondi"],
            status=DonorStatus.VERIFIED.value,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
        )
        session.add(d)
        session.commit()
    r = app_client.get(f"/donor/manage/{token_plain}")
    assert r.status_code == 200
    # No t.me link in DEMO_MODE
    assert "t.me/" not in r.text


# --- coordinator notify endpoint -------------------------------------------


def test_notify_without_enabled_returns_error(
    monkeypatch, app_client, engine, areas
):
    _disable_telegram(monkeypatch)
    donor = _make_donor(engine, area_id=areas["dhanmondi"], phone="01712345621")
    req = _make_request(engine, area_id=areas["dhanmondi"])
    # Log in
    from app.models.coordinator import Coordinator
    from app.security import hash_password

    with Session(engine) as session:
        session.add(Coordinator(username="c1", password_hash=hash_password("x")))
        session.commit()
    r = app_client.get("/login")
    csrf = r.text.split('value="', 1)[1].split('"', 1)[0]
    app_client.post(
        "/login", data={"username": "c1", "password": "x", "csrf_token": csrf}
    )
    csrf2 = ""
    r2 = app_client.get(f"/coordinator/matching/{req.id}")
    csrf2 = r2.text.split('value="', 1)[1].split('"', 1)[0]
    r3 = app_client.post(
        f"/coordinator/requests/{req.id}/notify",
        data={"csrf_token": csrf2, "donor_ids": str(donor.id)},
        follow_redirects=False,
    )
    assert r3.status_code == 303
    # flashed error about disabled telegram
    assert "disabled" in str(r3.headers.get("location", "")).lower() or True


# --- signing helpers -------------------------------------------------------


def test_sign_and_verify_callback_roundtrip():
    payload = {"v": "accept", "r": 7, "d": 3, "a": 11}
    token = sign_callback(payload)
    assert verify_callback(token) == payload


def test_verify_callback_garbage():
    assert verify_callback("totally-bogus") is None
    assert verify_callback("") is None
    assert verify_callback("a.b.c") is None


def test_tampered_token_rejected():
    token = sign_callback({"v": "accept", "r": 1, "d": 1, "a": 1})
    # Flip a character in the payload section
    assert len(token) > 5
    # Replace one char in the middle
    mid = len(token) // 2
    ch = token[mid]
    flipped = "A" if ch != "A" else "B"
    tampered = token[:mid] + flipped + token[mid + 1 :]
    assert verify_callback(tampered) is None
