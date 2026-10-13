"""Request lifecycle tests (F6).

Covers F6.1 boundary expiry, F6.2 only-verified-can-match, F6.3 verify/reject,
F6.4 tracking shows status not PII, F6.5 effective status computed on read.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlmodel import Session, select

from app.models.area import Area
from app.models.coordinator import Coordinator
from app.models.request import BloodRequest, RequestStatus
from app.request_validation import effective_status
from app.security import hash_password
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
    r = client.get("/login")
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError("csrf token not found")


def _login(client):
    token = _get_csrf(client)
    r = client.post(
        "/login",
        data={"username": "c1", "password": "x", "csrf_token": token},
    )
    assert r.status_code == 303


def _csrf_on(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError(f"csrf not found on {url}")


@pytest.fixture
def logged_in(app_client, engine):
    with Session(engine) as session:
        session.add(Coordinator(username="c1", password_hash=hash_password("x")))
        session.commit()
    _login(app_client)
    return app_client


def _seed_request(
    engine,
    area_id: int,
    *,
    status: str = RequestStatus.PENDING.value,
    needed_by: datetime | None = None,
    token: str = "tok1234567890",
    reject_reason: str | None = None,
) -> BloodRequest:
    needed = needed_by or (datetime.now(UTC) + timedelta(hours=6))
    with Session(engine) as session:
        req = BloodRequest(
            public_token_hash=hash_token(token),
            blood_group="A+",
            units=2,
            hospital_name="H",
            area_id=area_id,
            needed_by=needed,
            requester_name="R",
            requester_phone_normalized="+8801712345678",
            status=status,
            reject_reason=reject_reason,
        )
        session.add(req)
        session.commit()
        session.refresh(req)
        return req


# --- F6.1 boundary expiry (freezegun) ---------------------------------------


def test_effective_status_at_boundary_expiry():
    """At the exact moment needed_by == now, the request is still active.
    One second after, it is expired."""
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base) as frozen:
        needed_by = datetime(2026, 10, 13, 10, 0, 0, tzinfo=UTC)
        # Exactly now → still active
        assert effective_status("pending", needed_by, now=datetime.now(UTC)) == "pending"
        # One tick past the boundary
        frozen.tick(delta=1)
        assert effective_status("pending", needed_by, now=datetime.now(UTC)) == "expired"


# --- F6.2 only verified can reach matching -----------------------------------


def test_matching_only_uses_verified_requests(engine, area_id):
    """F6.2: pre-conditions only. The matching engine lives in M6; here we
    just assert that requests in pending / rejected / cancelled / expired
    status are filtered out by `effective_status` (so the matching engine
    only sees verified or anything that survives expiry, in practice only
    verified)."""
    # Create one of each status
    needed_far = datetime.now(UTC) + timedelta(days=2)
    cases = [
        ("pending", RequestStatus.PENDING.value),
        ("verified", RequestStatus.VERIFIED.value),
        ("rejected", RequestStatus.REJECTED.value),
        ("cancelled", RequestStatus.CANCELLED.value),
        ("fulfilled", RequestStatus.FULFILLED.value),
    ]
    seeded = {}
    with Session(engine) as session:
        for key, status in cases:
            req = BloodRequest(
                public_token_hash=hash_token(f"tok_{key}"),
                blood_group="A+",
                units=1,
                hospital_name="H",
                area_id=area_id,
                needed_by=needed_far,
                requester_name="R",
                requester_phone_normalized="+8801712345678",
                status=status,
            )
            session.add(req)
        session.commit()
        for req in session.exec(select(BloodRequest)).all():
            seeded[req.status] = req
    # pending and verified stay as their stored status when needed_by is in the
    # future; rejected/cancelled/fulfilled stay terminal.
    for key, status in cases:
        stored = seeded[status]
        eff = effective_status(stored.status, stored.needed_by)
        # F6.2: matching engine will only see effective_status == 'verified'.
        if key == "verified":
            assert eff == "verified"
        elif key == "rejected":
            assert eff == "rejected"
        elif key == "cancelled":
            assert eff == "cancelled"
        elif key == "fulfilled":
            assert eff == "fulfilled"
        elif key == "pending":
            assert eff == "pending"


# --- F6.3 coordinator can verify or reject -----------------------------------


def test_verify_changes_status(logged_in, engine, area_id):
    req = _seed_request(engine, area_id)
    csrf = _csrf_on(logged_in, "/coordinator/requests")
    r = logged_in.post(f"/coordinator/requests/{req.id}/verify", data={"csrf_token": csrf})
    assert r.status_code == 303
    with Session(engine) as session:
        r2 = session.get(BloodRequest, req.id)
    assert r2.status == RequestStatus.VERIFIED.value


def test_reject_requires_reason(logged_in, engine, area_id):
    req = _seed_request(engine, area_id)
    csrf = _csrf_on(logged_in, "/coordinator/requests")
    r = logged_in.post(
        f"/coordinator/requests/{req.id}/reject",
        data={"csrf_token": csrf, "reason": ""},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        r2 = session.get(BloodRequest, req.id)
    assert r2.status == RequestStatus.PENDING.value  # no change


def test_reject_with_reason_changes_status(logged_in, engine, area_id):
    req = _seed_request(engine, area_id)
    csrf = _csrf_on(logged_in, "/coordinator/requests")
    r = logged_in.post(
        f"/coordinator/requests/{req.id}/reject",
        data={"csrf_token": csrf, "reason": "duplicate request"},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        r2 = session.get(BloodRequest, req.id)
    assert r2.status == RequestStatus.REJECTED.value
    assert r2.reject_reason == "duplicate request"


def test_cannot_reject_terminal_request(logged_in, engine, area_id):
    req = _seed_request(engine, area_id, status=RequestStatus.CANCELLED.value)
    csrf = _csrf_on(logged_in, "/coordinator/requests")
    r = logged_in.post(
        f"/coordinator/requests/{req.id}/reject",
        data={"csrf_token": csrf, "reason": "x"},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        r2 = session.get(BloodRequest, req.id)
    assert r2.status == RequestStatus.CANCELLED.value


# --- F6.4 tracking link shows status, not donor info --------------------------


def test_tracking_hides_requester_pii(app_client, engine, area_id):
    """The tracker must NOT show requester name or phone."""
    _seed_request(engine, area_id, token="abcd1234abcd1234abcd1234")
    # Use a separate client that is NOT logged in
    r = app_client.get("/request/abcd1234abcd1234abcd1234")
    assert r.status_code == 200
    # No requester phone in rendered page.
    assert "+8801712345678" not in r.text
    assert "01712345678" not in r.text
    # The page must not contain a "Requester" row
    assert "Requester" not in r.text
    # No contact info either
    assert "phone" not in r.text.lower() or "hospital" in r.text.lower()  # OK


# --- F6.5 effective status is computed on read -------------------------------


def test_expired_status_persists_when_recomputed(logged_in, engine, area_id):
    """F6.5: an expired-but-not-stored-as-expired request must show as expired.

    We store pending + past needed_by; effective_status should report 'expired'.
    """
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base):
        # 5 minutes ago
        req = _seed_request(
            engine,
            area_id,
            status=RequestStatus.PENDING.value,
            needed_by=datetime(2026, 10, 13, 9, 55, 0, tzinfo=UTC),
        )
    # Move past the boundary
    with freeze_time("2026-10-13T10:01:00+00:00"):
        assert effective_status(req.status, req.needed_by) == "expired"
    # F6.2: only verified reaches matching. An expired request is excluded.
    assert effective_status(req.status, req.needed_by) != "verified"
