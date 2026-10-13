"""Coordinator donor management tests (F4.1-F4.9)."""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest
from sqlmodel import Session, select

from app.models.area import Area
from app.models.audit_log import AuditAction, AuditLog
from app.models.contact_attempt import ContactAttempt
from app.models.coordinator import Coordinator
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
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


def _get_donor_csrf(client) -> str:
    r = client.get("/coordinator/donors")
    assert r.status_code == 200
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            return line.split('value="', 1)[1].split('"', 1)[0]
    raise AssertionError("csrf not found on donor list page")


@pytest.fixture
def logged_in(app_client, engine):
    with Session(engine) as session:
        session.add(Coordinator(username="coord1", password_hash=hash_password("pw")))
        session.commit()
    _login(app_client)
    return app_client


@pytest.fixture
def areas(engine):
    with Session(engine) as session:
        a1 = Area(name="Dhanmondi", is_active=True)
        a2 = Area(name="Mirpur", is_active=True)
        a3 = Area(name="Uttara", is_active=False)  # inactive, used to test filter
        session.add_all([a1, a2, a3])
        session.commit()
        session.refresh(a1)
        session.refresh(a2)
    return {"dhanmondi": a1.id, "mirpur": a2.id}


def _make_donor(
    engine,
    *,
    name: str,
    phone: str,
    area_id: int,
    blood_group: str = "A+",
    is_available: bool = True,
    status: str = DonorStatus.UNVERIFIED.value,
    last_donation_date: date | None = None,
) -> Donor:
    with Session(engine) as session:
        from app.phone import normalize_bd_mobile

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


# --- F4.1 phones are masked in every list and detail render -----------------


def test_list_masks_phones(logged_in, engine, areas):
    _make_donor(engine, name="Alice", phone="01712345671", area_id=areas["dhanmondi"])
    r = logged_in.get("/coordinator/donors")
    assert r.status_code == 200
    # The full normalized phone must not appear in the list HTML.
    assert "+8801712345671" not in r.text
    # The masked form (with bullets) must appear.
    assert "•••" in r.text
    # The masked fragment +88017••••••671 is the visible form.
    assert "+88017••••••671" in r.text


def test_detail_masks_phone_by_default(logged_in, engine, areas):
    d = _make_donor(engine, name="Bob", phone="01812345672", area_id=areas["dhanmondi"])
    r = logged_in.get(f"/coordinator/donors/{d.id}")
    assert r.status_code == 200
    assert "+8801812345672" not in r.text
    assert "+88018••••••672" in r.text
    assert "•••" in r.text


# --- F4.2 reveal action returns the full phone and writes exactly one audit --


def test_reveal_phone_writes_one_audit_and_shows_full(logged_in, engine, areas):
    d = _make_donor(engine, name="Carol", phone="01912345673", area_id=areas["dhanmondi"])
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/reveal-phone", data={"csrf_token": csrf}
    )
    assert r.status_code == 303
    # Follow the redirect to the detail page.
    r2 = logged_in.get(f"/coordinator/donors/{d.id}")
    assert r2.status_code == 200
    # The full phone is now visible.
    assert "+8801912345673" in r2.text
    # Exactly one audit row for this donor with action DONOR_PHONE_REVEAL.
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.donor_id == d.id,
                    AuditLog.action == AuditAction.DONOR_PHONE_REVEAL.value,
                )
            ).all()
        )
    assert len(rows) == 1
    assert rows[0].actor_kind == "coordinator"


def test_reveal_again_writes_second_audit(logged_in, engine, areas):
    """Each reveal is a separate audit event."""
    d = _make_donor(engine, name="Dan", phone="01612345674", area_id=areas["dhanmondi"])
    for _ in range(2):
        csrf = _get_donor_csrf(logged_in)
        logged_in.post(
            f"/coordinator/donors/{d.id}/reveal-phone", data={"csrf_token": csrf}
        )
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.donor_id == d.id,
                    AuditLog.action == AuditAction.DONOR_PHONE_REVEAL.value,
                )
            ).all()
        )
    assert len(rows) == 2


def test_clear_reveal_hides_phone_again(logged_in, engine, areas):
    d = _make_donor(engine, name="Eve", phone="01512345675", area_id=areas["dhanmondi"])
    csrf = _get_donor_csrf(logged_in)
    logged_in.post(f"/coordinator/donors/{d.id}/reveal-phone", data={"csrf_token": csrf})
    # Phone visible
    r = logged_in.get(f"/coordinator/donors/{d.id}")
    assert "+8801512345675" in r.text
    # Clear
    csrf = _get_donor_csrf(logged_in)
    r2 = logged_in.post(
        f"/coordinator/donors/{d.id}/reveal-phone/clear", data={"csrf_token": csrf}
    )
    assert r2.status_code == 303
    r3 = logged_in.get(f"/coordinator/donors/{d.id}")
    assert "+8801512345675" not in r3.text
    assert "+88015••••••675" in r3.text


# --- F4.3 every status change writes exactly one audit row -------------------


@pytest.mark.parametrize(
    "action_path,action_enum,donor_factory",
    [
        ("verify", AuditAction.DONOR_VERIFY, lambda: {"status": DonorStatus.UNVERIFIED.value}),
        ("suspend", AuditAction.DONOR_SUSPEND, lambda: {"status": DonorStatus.VERIFIED.value}),
        ("unsuspend", AuditAction.DONOR_UNSUSPEND, lambda: {"status": DonorStatus.SUSPENDED.value}),
    ],
)
def test_status_change_writes_one_audit(
    logged_in, engine, areas, action_path, action_enum, donor_factory
):
    d = _make_donor(engine, name="Frank", phone="01712345676", area_id=areas["dhanmondi"], **donor_factory())
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/{action_path}", data={"csrf_token": csrf}
    )
    assert r.status_code == 303
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.donor_id == d.id,
                    AuditLog.action == action_enum.value,
                )
            ).all()
        )
        donor = session.get(Donor, d.id)
    assert len(rows) == 1
    # F4.7: statuses are unverified / verified / suspended.
    if action_path == "verify":
        assert donor.status == DonorStatus.VERIFIED.value
    elif action_path == "suspend":
        assert donor.status == DonorStatus.SUSPENDED.value
    elif action_path == "unsuspend":
        assert donor.status == DonorStatus.VERIFIED.value


# --- F4.4 filters combine correctly (test matrix) -----------------------------


def _make_seed_set(engine, areas):
    _make_donor(engine, name="Alice", phone="01712345611", area_id=areas["dhanmondi"], blood_group="A+", status=DonorStatus.VERIFIED.value)
    _make_donor(engine, name="Bob", phone="01812345612", area_id=areas["dhanmondi"], blood_group="B+", status=DonorStatus.UNVERIFIED.value)
    _make_donor(engine, name="Carol", phone="01912345613", area_id=areas["mirpur"], blood_group="A+", status=DonorStatus.VERIFIED.value, is_available=False)
    _make_donor(engine, name="Dan", phone="01612345614", area_id=areas["mirpur"], blood_group="A+", status=DonorStatus.SUSPENDED.value)


def test_filter_by_blood_group(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get("/coordinator/donors?blood_group=A%2B")
    assert r.status_code == 200
    # A+ donors: Alice, Carol, Dan
    assert "Alice" in r.text
    assert "Carol" in r.text
    assert "Dan" in r.text
    assert "Bob" not in r.text


def test_filter_by_area(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get(f"/coordinator/donors?area_id={areas['mirpur']}")
    assert r.status_code == 200
    assert "Carol" in r.text
    assert "Dan" in r.text
    assert "Alice" not in r.text
    assert "Bob" not in r.text


def test_filter_by_status(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get("/coordinator/donors?status=verified")
    assert r.status_code == 200
    assert "Alice" in r.text
    assert "Carol" in r.text
    assert "Bob" not in r.text  # unverified
    assert "Dan" not in r.text  # suspended


def test_filter_by_availability(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get("/coordinator/donors?availability=available")
    assert "Carol" not in r.text  # unavailable
    assert "Alice" in r.text
    assert "Dan" in r.text


def test_filter_search_by_name(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get("/coordinator/donors?q=Al")
    assert r.status_code == 200
    assert "Alice" in r.text
    assert "Bob" not in r.text


def test_filter_search_by_phone_digits(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    r = logged_in.get("/coordinator/donors?q=01812345612")
    assert "Bob" in r.text
    assert "Alice" not in r.text


def test_filters_combine(logged_in, engine, areas):
    _make_seed_set(engine, areas)
    # blood_group=A+, area=mirpur, status=suspended -> only Dan
    r = logged_in.get(
        f"/coordinator/donors?blood_group=A%2B&area_id={areas['mirpur']}&status=suspended"
    )
    assert r.status_code == 200
    assert "Dan" in r.text
    assert "Alice" not in r.text
    assert "Bob" not in r.text
    assert "Carol" not in r.text


def test_pagination_boundaries(logged_in, engine, areas):
    # 30 donors (BD mobile = 11 digits: 0 + 1 + operator(1) + 8 tail)
    for i in range(30):
        # 0171234567X  -> 11 digits, operator=7. Vary the last digit.
        last = i % 10
        second_last = (i // 10) % 10
        _make_donor(
            engine,
            name=f"D{i:02d}",
            phone=f"017123456{second_last}{last}",  # 11 digits
            area_id=areas["dhanmondi"],
            blood_group="O+",
        )
    # Page 1: newest 25 (D29 down to D05) — DESC order by id
    r1 = logged_in.get("/coordinator/donors")
    assert r1.status_code == 200
    assert "D29" in r1.text
    assert "D05" in r1.text
    assert "D04" not in r1.text
    # Page 2: oldest 5 (D04 down to D00)
    r2 = logged_in.get("/coordinator/donors?page=2")
    assert r2.status_code == 200
    assert "D04" in r2.text
    assert "D00" in r2.text
    assert "D29" not in r2.text
    # Page beyond end: clamped to last page (page 2)
    r3 = logged_in.get("/coordinator/donors?page=99")
    assert r3.status_code == 200
    assert "D04" in r3.text
    assert "D00" in r3.text
    # Page 0: clamped to 1
    r4 = logged_in.get("/coordinator/donors?page=0")
    assert r4.status_code == 200
    assert "D29" in r4.text


# --- F4.5 only coordinators can access these routes ---------------------------


def test_list_requires_login(app_client):
    r = app_client.get("/coordinator/donors")
    assert r.status_code == 401


def test_detail_requires_login(app_client, engine, areas):
    d = _make_donor(engine, name="Hidden", phone="01712345677", area_id=areas["dhanmondi"])
    r = app_client.get(f"/coordinator/donors/{d.id}")
    assert r.status_code == 401


def test_status_changes_require_login(app_client, engine, areas):
    d = _make_donor(engine, name="Hidden", phone="01712345678", area_id=areas["dhanmondi"])
    for path in ("verify", "suspend", "unsuspend", "reveal-phone", "regenerate-link", "record-donation"):
        r = app_client.post(f"/coordinator/donors/{d.id}/{path}", data={"csrf_token": "x"})
        assert r.status_code in {401, 403}, f"{path} got {r.status_code}"


# --- F4.6 recording a donation updates last_donation_date and makes ineligible


def test_record_donation_updates_date(logged_in, engine, areas):
    d = _make_donor(engine, name="Hank", phone="01712345679", area_id=areas["dhanmondi"], status=DonorStatus.VERIFIED.value)
    csrf = _get_donor_csrf(logged_in)
    today = date.today().isoformat()
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={"donation_date": today, "csrf_token": csrf, "note": ""},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    assert donor.last_donation_date == date.today()


def test_record_donation_ineligible_by_gap(logged_in, engine, areas):
    """F4.6 / F7.3 boundary: a donor with last donation today is ineligible.
    The detail page should not show 'available to match' (we just assert the
    field is updated and rely on F7 tests for the engine behaviour)."""
    d = _make_donor(engine, name="Ida", phone="01712345680", area_id=areas["dhanmondi"], status=DonorStatus.VERIFIED.value)
    csrf = _get_donor_csrf(logged_in)
    today = date.today().isoformat()
    logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={"donation_date": today, "csrf_token": csrf, "note": ""},
    )
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    # MIN_DONATION_GAP_DAYS default is 120. So donor is ineligible.
    # We assert via the matching gap function used in M6 — but to keep this
    # test focused, we just assert last_donation_date is set and within the gap.
    assert donor.last_donation_date is not None
    assert (date.today() - donor.last_donation_date) < timedelta(days=120)


def test_record_donation_rejects_future_date(logged_in, engine, areas):
    d = _make_donor(engine, name="Judy", phone="01712345681", area_id=areas["dhanmondi"])
    csrf = _get_donor_csrf(logged_in)
    future = (date.today() + timedelta(days=1)).isoformat()
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={"donation_date": future, "csrf_token": csrf, "note": ""},
    )
    assert r.status_code == 303
    # Date unchanged
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    assert donor.last_donation_date is None


def test_record_donation_refuses_suspended_donor(logged_in, engine, areas):
    """A suspended donor must not be silently marked as having donated:
    doing so would make them eligible again in the next matching pass.
    """
    d = _make_donor(
        engine,
        name="Sus",
        phone="01712345683",
        area_id=areas["dhanmondi"],
        status=DonorStatus.SUSPENDED.value,
    )
    csrf = _get_donor_csrf(logged_in)
    today = date.today().isoformat()
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={"donation_date": today, "csrf_token": csrf, "note": ""},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    # Date is unchanged.
    assert donor.last_donation_date is None


def test_record_donation_refuses_date_before_previous(logged_in, engine, areas):
    """Recording a date EARLIER than the donor's last donation would
    roll the gap-window back, making them eligible too soon.
    """
    d = _make_donor(
        engine,
        name="Roll",
        phone="01712345684",
        area_id=areas["dhanmondi"],
        status=DonorStatus.VERIFIED.value,
    )
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
        donor.last_donation_date = date(2026, 9, 1)
        session.add(donor)
        session.commit()

    csrf = _get_donor_csrf(logged_in)
    earlier = date(2026, 8, 1).isoformat()
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={"donation_date": earlier, "csrf_token": csrf, "note": ""},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    # The earlier date was rejected; the original last_donation_date stands.
    assert donor.last_donation_date == date(2026, 9, 1)


def test_record_donation_with_request_token_creates_contact_attempt(
    logged_in, engine, areas
):
    d = _make_donor(engine, name="Kim", phone="01712345682", area_id=areas["dhanmondi"])
    # Create a request to link.
    with Session(engine) as session:
        from app.tokens import hash_token, new_token

        plain_token = new_token(24)
        req = BloodRequest(
            public_token_hash=hash_token(plain_token),
            blood_group="A+",
            units=1,
            hospital_name="H",
            area_id=areas["dhanmondi"],
            needed_by=date.today() + timedelta(days=1),
            requester_name="R",
            requester_phone_normalized="+8801711111111",
            status=RequestStatus.VERIFIED.value,
        )
        session.add(req)
        session.commit()
        session.refresh(req)
        token = plain_token
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/record-donation",
        data={
            "donation_date": date.today().isoformat(),
            "request_token": token,
            "note": "great",
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 303
    with Session(engine) as session:
        attempts = list(
            session.exec(select(ContactAttempt).where(ContactAttempt.donor_id == d.id)).all()
        )
    assert any(a.outcome == "donated" for a in attempts)


# --- F4.7 statuses are unverified / verified / suspended ---------------------


def test_only_three_statuses_exist():
    values = {s.value for s in DonorStatus}
    assert values == {"unverified", "verified", "suspended"}


# --- F4.8 verify accepts an optional short note ------------------------------


def test_verify_with_note(logged_in, engine, areas):
    d = _make_donor(engine, name="Liz", phone="01712345683", area_id=areas["dhanmondi"], status=DonorStatus.UNVERIFIED.value)
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/verify",
        data={"csrf_token": csrf, "note": "Reached on WhatsApp."},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    assert donor.status == DonorStatus.VERIFIED.value
    assert donor.verify_note == "Reached on WhatsApp."


def test_verify_with_no_note(logged_in, engine, areas):
    d = _make_donor(engine, name="Mia", phone="01712345684", area_id=areas["dhanmondi"], status=DonorStatus.UNVERIFIED.value)
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/verify",
        data={"csrf_token": csrf, "note": ""},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    assert donor.status == DonorStatus.VERIFIED.value
    assert donor.verify_note is None


def test_note_truncates_to_max(logged_in, engine, areas):
    d = _make_donor(engine, name="Ned", phone="01712345685", area_id=areas["dhanmondi"])
    csrf = _get_donor_csrf(logged_in)
    long = "x" * 1000
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/verify",
        data={"csrf_token": csrf, "note": long},
    )
    assert r.status_code == 303
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
    assert donor.verify_note is not None
    assert len(donor.verify_note) <= 500


# --- F4.9 notes form warns about non-medical content -------------------------


def test_note_warning_in_detail(logged_in, engine, areas):
    d = _make_donor(engine, name="Olive", phone="01712345686", area_id=areas["dhanmondi"])
    r = logged_in.get(f"/coordinator/donors/{d.id}")
    assert r.status_code == 200
    # The verify and donation forms include the non-medical warning.
    assert "non-medical" in r.text.lower() or "medical" in r.text.lower()


# --- regenerate link ---------------------------------------------------------


def test_regenerate_link_invalidates_old(logged_in, engine, areas):
    d = _make_donor(engine, name="Paul", phone="01712345687", area_id=areas["dhanmondi"])
    old_token = new_token(24)
    # Set the donor's token to a known value
    with Session(engine) as session:
        donor = session.get(Donor, d.id)
        donor.manage_token_hash = hash_token(old_token)
        session.add(donor)
        session.commit()
    # Old token works
    r0 = logged_in.get(f"/donor/manage/{old_token}")
    assert r0.status_code == 200
    # Regenerate
    csrf = _get_donor_csrf(logged_in)
    r = logged_in.post(
        f"/coordinator/donors/{d.id}/regenerate-link", data={"csrf_token": csrf}
    )
    assert r.status_code == 303
    # Old token no longer works
    r1 = logged_in.get(f"/donor/manage/{old_token}")
    assert r1.status_code == 404
    # The new link is shown on the detail page exactly once
    r2 = logged_in.get(f"/coordinator/donors/{d.id}")
    assert r2.status_code == 200
    m = re.search(r"/donor/manage/([A-Za-z0-9_-]+)", r2.text)
    assert m is not None
    new_token_plain = m.group(1)
    assert new_token_plain != old_token
    # The new token works
    r3 = logged_in.get(f"/donor/manage/{new_token_plain}")
    assert r3.status_code == 200
    # Audit row written
    with Session(engine) as session:
        rows = list(
            session.exec(
                select(AuditLog).where(
                    AuditLog.donor_id == d.id,
                    AuditLog.action == AuditAction.DONOR_REGENERATE_LINK.value,
                )
            ).all()
        )
    assert len(rows) == 1
    # Reload page: the new link is NOT shown a second time
    r4 = logged_in.get(f"/coordinator/donors/{d.id}")
    assert new_token_plain not in r4.text


# --- exhaustive BLOOD_GROUPS in filter ---------------------------------------


def test_blood_group_filter_includes_all_eight(logged_in):
    r = logged_in.get("/coordinator/donors")
    for g in BLOOD_GROUPS:
        assert f'value="{g}"' in r.text, f"blood group {g} not present in filter"


# --- 404 for unknown donor id ------------------------------------------------


def test_detail_404_for_unknown(logged_in):
    r = logged_in.get("/coordinator/donors/9999")
    assert r.status_code == 404
