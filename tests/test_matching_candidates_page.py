"""Coordinator matching route tests (F7.7).

The page lists ranked candidates with masked phones and lets the coordinator
record contact attempts per donor. Marking 'donated' closes the request
and updates the donor's last_donation_date.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app.models.area import Area
from app.models.audit_log import AuditAction, AuditLog
from app.models.contact_attempt import ContactAttempt, ContactOutcome
from app.models.coordinator import Coordinator
from app.models.donor import Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
from app.phone import normalize_bd_mobile
from app.security import hash_password
from app.tokens import hash_token, new_token

# --- helpers ----------------------------------------------------------------


def _get_csrf(client) -> str:
    r = client.get("/login")
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError("csrf token not found")


def _login(client, username: str = "coord1", password: str = "pw") -> None:
    token = _get_csrf(client)
    r = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
    )
    assert r.status_code == 303, f"login failed: {r.status_code} {r.text!r}"


def _page_csrf(client, url: str) -> str:
    r = client.get(url)
    assert r.status_code == 200, f"failed to GET {url}: {r.status_code}"
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError(f"csrf not found on {url}")


@pytest.fixture
def areas(engine):
    with Session(engine) as session:
        a1 = Area(name="Dhanmondi", is_active=True)
        a2 = Area(name="Mirpur", is_active=True)
        session.add_all([a1, a2])
        session.commit()
        session.refresh(a1)
        session.refresh(a2)
    return {"dhanmondi": a1.id, "mirpur": a2.id}


@pytest.fixture
def logged_in(app_client, engine):
    with Session(engine) as session:
        session.add(Coordinator(username="coord1", password_hash=hash_password("pw")))
        session.commit()
    _login(app_client)
    return app_client


def _make_donor(
    engine,
    *,
    name: str,
    phone: str,
    area_id: int,
    blood_group: str = "A+",
    is_available: bool = True,
    status: str = DonorStatus.VERIFIED.value,
    last_donation_date: date | None = None,
) -> Donor:
    with Session(engine) as session:
        d = Donor(
            manage_token_hash=hash_token(new_token(24)),
            name=name,
            blood_group=blood_group,
            phone_normalized=normalize_bd_mobile(phone),
            area_id=area_id,
            last_donation_date=last_donation_date,
            is_available=is_available,
            status=status,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
        )
        session.add(d)
        session.commit()
        session.refresh(d)
    return d


def _make_request(
    engine,
    *,
    area_id: int,
    blood_group: str = "A+",
    needed_by: datetime | None = None,
    status: str = RequestStatus.VERIFIED.value,
) -> BloodRequest:
    nb = needed_by or (datetime.now(UTC) + timedelta(hours=6))
    with Session(engine) as session:
        req = BloodRequest(
            public_token_hash=hash_token(new_token(24)),
            blood_group=blood_group,
            units=2,
            hospital_name="H",
            area_id=area_id,
            needed_by=nb,
            requester_name="R",
            requester_phone_normalized="+8801712345678",
            status=status,
        )
        session.add(req)
        session.commit()
        session.refresh(req)
    return req


# --- page renders -----------------------------------------------------------


def test_candidates_page_renders(logged_in, engine, areas):
    _make_donor(
        engine, name="Alice", phone="01712345611", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    r = logged_in.get(f"/coordinator/matching/{req.id}")
    assert r.status_code == 200
    assert "Alice" in r.text
    # masked phone
    assert "+88017••••••" in r.text
    # full phone MUST NOT appear
    assert "+8801712345611" not in r.text
    assert "01712345611" not in r.text


def test_candidates_page_requires_login(app_client, engine, areas):
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    r = app_client.get(f"/coordinator/matching/{req.id}")
    assert r.status_code == 401


def test_candidates_page_for_pending_request_redirects(logged_in, engine, areas):
    req = _make_request(
        engine,
        area_id=areas["dhanmondi"],
        blood_group="A+",
        status=RequestStatus.PENDING.value,
    )
    r = logged_in.get(f"/coordinator/matching/{req.id}", follow_redirects=False)
    assert r.status_code == 303
    assert f"/coordinator/requests/{req.id}" in r.headers.get("location", "")


def test_candidates_page_for_404(logged_in, engine):
    r = logged_in.get("/coordinator/matching/99999")
    assert r.status_code == 404


def test_candidates_page_renders_all_donors(logged_in, engine, areas):
    # 5 donors across 2 areas, mix of eligible/ineligible
    _make_donor(
        engine, name="A", phone="01712345611", area_id=areas["dhanmondi"]
    )
    _make_donor(
        engine,
        name="B",
        phone="01712345612",
        area_id=areas["mirpur"],
        blood_group="O-",
    )
    _make_donor(
        engine,
        name="C",
        phone="01712345613",
        area_id=areas["dhanmondi"],
        status=DonorStatus.SUSPENDED.value,
    )
    _make_donor(
        engine,
        name="D",
        phone="01712345614",
        area_id=areas["dhanmondi"],
        is_available=False,
    )
    _make_donor(
        engine,
        name="E",
        phone="01712345615",
        area_id=areas["dhanmondi"],
        blood_group="B+",  # incompatible with A+
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    r = logged_in.get(f"/coordinator/matching/{req.id}")
    assert r.status_code == 200
    for name in ("A", "B", "C", "D", "E"):
        assert name in r.text


# --- record contact attempt -------------------------------------------------


def test_record_contact_attempt(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="X", phone="01712345621", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/contact",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "outcome": ContactOutcome.CONTACTED.value,
            "note": "left voicemail",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        attempts = list(
            session.exec(
                select(ContactAttempt).where(ContactAttempt.request_id == req.id)
            ).all()
        )
    assert len(attempts) == 1
    assert attempts[0].outcome == "contacted"
    assert attempts[0].note == "left voicemail"
    # audit row
    with Session(engine) as session:
        audits = list(
            session.exec(
                select(AuditLog).where(AuditLog.action == AuditAction.CONTACT_ATTEMPT.value)
            ).all()
        )
    assert len(audits) == 1
    assert audits[0].donor_id == donor.id
    assert audits[0].request_id == req.id
    assert audits[0].detail == "contacted"


def test_record_donated_outcome_via_form_rejected(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="Y", phone="01712345622", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/contact",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "outcome": "donated",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        attempts = list(
            session.exec(
                select(ContactAttempt).where(ContactAttempt.request_id == req.id)
            ).all()
        )
    assert attempts == []


def test_record_contact_invalid_donor_404(logged_in, engine, areas):
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/contact",
        data={
            "csrf_token": csrf,
            "donor_id": "99999",
            "outcome": "contacted",
        },
        follow_redirects=False,
    )
    assert r.status_code == 404


# --- mark donated -----------------------------------------------------------


def test_mark_donated_creates_attempt_and_closes_request(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="Z", phone="01712345631", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    today = date.today().isoformat()
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/donated",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "donation_date": today,
            "note": "thanks!",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.get(Donor, donor.id)
        r2 = session.get(BloodRequest, req.id)
        attempts = list(
            session.exec(
                select(ContactAttempt).where(ContactAttempt.request_id == req.id)
            ).all()
        )
    assert d.last_donation_date == date.today()
    assert r2.status == RequestStatus.FULFILLED.value
    assert r2.closed_at is not None
    assert len(attempts) == 1
    assert attempts[0].outcome == "donated"
    assert attempts[0].note == "thanks!"


def test_mark_donated_with_existing_attempt_updates_outcome(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="W", phone="01712345632", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    with Session(engine) as session:
        coord = session.exec(select(Coordinator).where(Coordinator.username == "coord1")).first()
        assert coord is not None
        a = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=coord.id,
            outcome="contacted",
        )
        session.add(a)
        session.commit()
        session.refresh(a)
        attempt_id = a.id

    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/contact/{attempt_id}/donated",
        data={"csrf_token": csrf, "donation_date": date.today().isoformat()},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        a = session.get(ContactAttempt, attempt_id)
        r2 = session.get(BloodRequest, req.id)
    assert a.outcome == "donated"
    assert r2.status == RequestStatus.FULFILLED.value


def test_mark_donated_invalid_date(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="V", phone="01712345633", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/donated",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "donation_date": "not-a-date",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.get(Donor, donor.id)
        r2 = session.get(BloodRequest, req.id)
    assert d.last_donation_date is None
    assert r2.status == RequestStatus.VERIFIED.value


def test_mark_donated_future_date_rejected(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="U", phone="01712345634", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    future = (date.today() + timedelta(days=2)).isoformat()
    r = logged_in.post(
        f"/coordinator/matching/{req.id}/donated",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "donation_date": future,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as session:
        d = session.get(Donor, donor.id)
    assert d.last_donation_date is None


def test_mark_donated_unknown_request_404(logged_in, engine, areas):
    csrf = _page_csrf(logged_in, "/coordinator/requests")
    r = logged_in.post(
        "/coordinator/matching/99999/donated",
        data={"csrf_token": csrf, "donor_id": "1", "donation_date": "2026-01-01"},
        follow_redirects=False,
    )
    assert r.status_code == 404


# --- CSRF protection --------------------------------------------------------


def test_post_without_csrf_is_rejected(app_client, engine, areas):
    donor = _make_donor(
        engine, name="Q", phone="01712345641", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    # Need a logged-in session
    with Session(engine) as session:
        session.add(Coordinator(username="coord1", password_hash=hash_password("pw")))
        session.commit()
    _login(app_client)
    r = app_client.post(
        f"/coordinator/matching/{req.id}/contact",
        data={"donor_id": str(donor.id), "outcome": "contacted"},
        follow_redirects=False,
    )
    assert r.status_code == 403


# --- 24h flag surfaced on page ---------------------------------------------


def test_recent_attempt_shows_recently_flag(logged_in, engine, areas):
    donor = _make_donor(
        engine, name="R", phone="01712345651", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    with Session(engine) as session:
        coord = session.exec(select(Coordinator).where(Coordinator.username == "coord1")).first()
        assert coord is not None
        a = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=coord.id,
            outcome="contacted",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        session.add(a)
        session.commit()

    r = logged_in.get(f"/coordinator/matching/{req.id}")
    assert r.status_code == 200
    # The page marks the recent column with a check
    assert ">✓<" in r.text


def test_mark_donated_idempotent_no_double_close(logged_in, engine, areas):
    """A second mark-donated call after the request is already FULFILLED
    must not re-close it, re-set last_donation_date, or add a second
    'donated' audit row.
    """
    donor = _make_donor(
        engine, name="I", phone="01712345639", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    today = date.today().isoformat()

    # First call: marks the request FULFILLED.
    r1 = logged_in.post(
        f"/coordinator/matching/{req.id}/donated",
        data={
            "csrf_token": csrf,
            "donor_id": str(donor.id),
            "donation_date": today,
            "note": "",
        },
        follow_redirects=False,
    )
    assert r1.status_code == 303
    with Session(engine) as session:
        d_after = session.get(Donor, donor.id)
        first_date = d_after.last_donation_date
        first_attempt_count = len(
            list(
                session.exec(
                    select(ContactAttempt).where(ContactAttempt.request_id == req.id)
                ).all()
            )
        )
    assert first_attempt_count == 1

    # Second call on a different donor: must be rejected, must NOT add a
    # second attempt, must NOT re-set last_donation_date.
    donor2 = _make_donor(
        engine, name="J", phone="01712345640", area_id=areas["dhanmondi"]
    )
    csrf2 = _page_csrf(logged_in, f"/coordinator/requests/{req.id}")
    r2 = logged_in.post(
        f"/coordinator/matching/{req.id}/donated",
        data={
            "csrf_token": csrf2,
            "donor_id": str(donor2.id),
            "donation_date": today,
            "note": "",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303
    with Session(engine) as session:
        d2 = session.get(Donor, donor.id)  # original donor
        attempts2 = list(
            session.exec(
                select(ContactAttempt).where(ContactAttempt.request_id == req.id)
            ).all()
        )
    # No new attempt was created.
    assert len(attempts2) == 1
    # last_donation_date on the original donor is unchanged.
    assert d2.last_donation_date == first_date


def test_mark_donated_refuses_declined_attempt(logged_in, engine, areas):
    """A donor who declined via Telegram must not be silently flipped to
    'donated' (F8.6 — idempotency for the donor's own response).
    """
    donor = _make_donor(
        engine, name="K", phone="01712345641", area_id=areas["dhanmondi"]
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    with Session(engine) as session:
        coord = session.exec(select(Coordinator).where(Coordinator.username == "coord1")).first()
        declined = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=coord.id,
            outcome="declined",
        )
        session.add(declined)
        session.commit()
        session.refresh(declined)
        declined_id = declined.id

    csrf = _page_csrf(logged_in, f"/coordinator/matching/{req.id}")
    logged_in.post(
        f"/coordinator/matching/{req.id}/contact/{declined_id}/donated",
        data={
            "csrf_token": csrf,
            "donation_date": date.today().isoformat(),
            "note": "",
        },
        follow_redirects=False,
    )
    # The route must reject the request (303 to a flash error page) and
    # leave the underlying state untouched: the declined attempt is
    # still declined and the request is not fulfilled.
    with Session(engine) as session:
        a = session.get(ContactAttempt, declined_id)
        r2 = session.get(BloodRequest, req.id)
    assert a.outcome == "declined"
    assert r2.status != RequestStatus.FULFILLED.value
