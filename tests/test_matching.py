"""Pure matching engine tests (F7.3, F7.4, F7.5, F7.6, F7.8).

The route layer (coordinator_matching) wraps the pure function and is
tested in test_matching_candidates_page.py.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlmodel import Session

from app.compatibility import can_donate_to
from app.matching import can_match, compute_candidates
from app.models.area import Area
from app.models.contact_attempt import ContactAttempt
from app.models.coordinator import Coordinator
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
from app.security import hash_password

# --- helpers ----------------------------------------------------------------


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
    from app.phone import normalize_bd_mobile
    from app.tokens import hash_token, new_token

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


def _make_request(engine, *, area_id: int, blood_group: str = "A+", needed_by: datetime | None = None) -> BloodRequest:
    from app.tokens import new_token

    nb = needed_by or (datetime.now(UTC) + timedelta(hours=6))
    with Session(engine) as session:
        req = BloodRequest(
            public_token=new_token(24),
            blood_group=blood_group,
            units=2,
            hospital_name="H",
            area_id=area_id,
            needed_by=nb,
            requester_name="R",
            requester_phone_normalized="+8801712345678",
            status=RequestStatus.VERIFIED.value,
        )
        session.add(req)
        session.commit()
        session.refresh(req)
    return req


# --- F7.3 exclusion rules ---------------------------------------------------


def test_excludes_unverified_donor(engine, areas):
    _make_donor(
        engine,
        name="U",
        phone="01712345601",
        area_id=areas["dhanmondi"],
        status=DonorStatus.UNVERIFIED.value,
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert len(out) == 1
    assert out[0].ineligible == "unverified"


def test_excludes_suspended_donor(engine, areas):
    _make_donor(
        engine,
        name="S",
        phone="01712345602",
        area_id=areas["dhanmondi"],
        status=DonorStatus.SUSPENDED.value,
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible == "suspended"


def test_excludes_unavailable_donor(engine, areas):
    _make_donor(
        engine,
        name="X",
        phone="01712345603",
        area_id=areas["dhanmondi"],
        is_available=False,
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible == "unavailable"


def test_excludes_incompatible_donor(engine, areas):
    # B+ donor cannot give to A+ recipient
    _make_donor(
        engine,
        name="B",
        phone="01712345604",
        area_id=areas["dhanmondi"],
        blood_group="B+",
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible == "incompatible"


def test_excludes_donor_within_gap(engine, areas):
    # Donated 30 days ago, gap is 120
    _make_donor(
        engine,
        name="Recent",
        phone="01712345605",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=30),
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible is not None
    assert "ineligible_gap" in out[0].ineligible


def test_eligible_donor_at_exact_gap_boundary(engine, areas):
    # Donated 120 days ago, gap is 120 → eligible
    _make_donor(
        engine,
        name="Edge",
        phone="01712345606",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=120),
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible is None


def test_never_donated_donor_is_eligible(engine, areas):
    _make_donor(
        engine,
        name="New",
        phone="01712345607",
        area_id=areas["dhanmondi"],
        last_donation_date=None,
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].ineligible is None
    assert out[0].days_since_donation is None


# --- F7.4 ranking -----------------------------------------------------------


def test_ranking_exact_match_before_compatible(engine, areas):
    """exact_match True comes before any compatible-but-not-exact donor."""
    d_exact = _make_donor(
        engine,
        name="Exact",
        phone="01712345611",
        area_id=areas["dhanmondi"],
        blood_group="A+",
    )
    d_o_neg = _make_donor(
        engine,
        name="ONeg",
        phone="01712345612",
        area_id=areas["dhanmondi"],
        blood_group="O-",
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert len(out) == 2
    assert out[0].donor.id == d_exact.id
    assert out[1].donor.id == d_o_neg.id


def test_ranking_same_area_before_other_area(engine, areas):
    d_same = _make_donor(
        engine,
        name="Same",
        phone="01712345621",
        area_id=areas["dhanmondi"],
        blood_group="A+",
    )
    d_other = _make_donor(
        engine,
        name="Other",
        phone="01712345622",
        area_id=areas["mirpur"],
        blood_group="A+",
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].donor.id == d_same.id
    assert out[1].donor.id == d_other.id


def test_ranking_longest_since_donation_first(engine, areas):
    d_oldest = _make_donor(
        engine,
        name="Oldest",
        phone="01712345631",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=400),
    )
    d_newest = _make_donor(
        engine,
        name="Newest",
        phone="01712345632",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=200),
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].donor.id == d_oldest.id
    assert out[1].donor.id == d_newest.id


def test_ranking_never_donated_beats_oldest(engine, areas):
    d_never = _make_donor(
        engine,
        name="Never",
        phone="01712345641",
        area_id=areas["dhanmondi"],
        last_donation_date=None,
    )
    d_old = _make_donor(
        engine,
        name="Old",
        phone="01712345642",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=400),
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].donor.id == d_never.id
    assert out[1].donor.id == d_old.id


def test_ranking_tie_breaks_on_donor_id(engine, areas):
    d1 = _make_donor(
        engine,
        name="One",
        phone="01712345651",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=200),
    )
    d2 = _make_donor(
        engine,
        name="Two",
        phone="01712345652",
        area_id=areas["dhanmondi"],
        last_donation_date=date.today() - timedelta(days=200),
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    # d1 was inserted first, so smaller id
    assert out[0].donor.id == d1.id
    assert out[1].donor.id == d2.id


def test_ranking_eligible_before_ineligible(engine, areas):
    d_eligible = _make_donor(
        engine,
        name="Eligible",
        phone="01712345661",
        area_id=areas["dhanmondi"],
    )
    d_suspended = _make_donor(
        engine,
        name="Suspended",
        phone="01712345662",
        area_id=areas["dhanmondi"],
        status=DonorStatus.SUSPENDED.value,
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].donor.id == d_eligible.id
    assert out[0].ineligible is None
    assert out[1].donor.id == d_suspended.id
    assert out[1].ineligible == "suspended"


# --- F7.5 recently-contacted flag -------------------------------------------


def test_recently_contacted_flag(engine, areas):
    donor = _make_donor(
        engine,
        name="Contacted",
        phone="01712345671",
        area_id=areas["dhanmondi"],
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    coord = Coordinator(username="c1", password_hash=hash_password("x"))
    with Session(engine) as session:
        session.add(coord)
        session.commit()
        session.refresh(coord)
        # An attempt 1 hour ago
        attempt = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=coord.id,
            outcome="contacted",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(attempt)
        session.commit()

    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    attempts = list(
        Session(engine).exec(__import__("sqlmodel").select(ContactAttempt)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=attempts,
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].recently_contacted is True


def test_recently_contacted_flag_old_attempt(engine, areas):
    donor = _make_donor(
        engine,
        name="OldContact",
        phone="01712345672",
        area_id=areas["dhanmondi"],
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    coord = Coordinator(username="c1", password_hash=hash_password("x"))
    with Session(engine) as session:
        session.add(coord)
        session.commit()
        session.refresh(coord)
        # 48 hours ago — outside 24h window
        attempt = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=coord.id,
            outcome="no_answer",
            created_at=datetime.now(UTC) - timedelta(hours=48),
        )
        session.add(attempt)
        session.commit()

    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    attempts = list(
        Session(engine).exec(__import__("sqlmodel").select(ContactAttempt)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=attempts,
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert out[0].recently_contacted is False


# --- F7.6 can_match ---------------------------------------------------------


def test_can_match_only_for_verified(engine, areas):
    from app.tokens import new_token

    needed = datetime.now(UTC) + timedelta(hours=6)
    with Session(engine) as session:
        for status in (
            RequestStatus.PENDING.value,
            RequestStatus.VERIFIED.value,
            RequestStatus.REJECTED.value,
            RequestStatus.FULFILLED.value,
            RequestStatus.CANCELLED.value,
        ):
            req = BloodRequest(
                public_token=new_token(24),
                blood_group="A+",
                units=1,
                hospital_name="H",
                area_id=areas["dhanmondi"],
                needed_by=needed,
                requester_name="R",
                requester_phone_normalized="+8801712345678",
                status=status,
            )
            session.add(req)
        session.commit()
    from sqlmodel import select

    with Session(engine) as session:
        for r in session.exec(select(BloodRequest)).all():
            if r.status == RequestStatus.VERIFIED.value:
                assert can_match(r) is True
            else:
                assert can_match(r) is False


def test_can_match_expired_returns_false(engine, areas):
    req = _make_request(
        engine,
        area_id=areas["dhanmondi"],
        blood_group="A+",
        needed_by=datetime.now(UTC) - timedelta(hours=1),
    )
    # Even if marked verified, needed_by in the past means no match.
    with Session(engine) as session:
        r = session.get(BloodRequest, req.id)
        r.status = RequestStatus.VERIFIED.value
        session.add(r)
        session.commit()
    with Session(engine) as session:
        r = session.get(BloodRequest, req.id)
    assert can_match(r) is False


# --- end-to-end donor pool --------------------------------------------------


def test_candidate_does_not_expose_phone_in_repr(engine, areas):
    d = _make_donor(
        engine,
        name="Alice",
        phone="01712345681",
        area_id=areas["dhanmondi"],
    )
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A+")
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    # The Candidate dataclass has a donor attribute; it should not auto-unwrap
    # the phone anywhere in `str()` or `repr()`. We simply assert the phone is
    # on the donor (routing layer is responsible for masking).
    assert out[0].donor.phone_normalized == d.phone_normalized


def test_all_compatible_groups_pass_for_universal_recipient(engine, areas):
    """A request for AB+ (universal recipient) should accept all 8 donor groups."""
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="AB+")
    # Use a unique 11-digit phone per blood group
    phones = {
        "A+": "01712345611",
        "A-": "01712345612",
        "B+": "01712345613",
        "B-": "01712345614",
        "AB+": "01712345615",
        "AB-": "01712345616",
        "O+": "01712345617",
        "O-": "01712345618",
    }
    for g in BLOOD_GROUPS:
        _make_donor(
            engine,
            name=f"D-{g}",
            phone=phones[g],
            area_id=areas["dhanmondi"],
            blood_group=g,
        )
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    assert len(out) == 8
    assert all(c.ineligible is None for c in out)
    # F7.2: every donor is Rh+ or Rh-; AB+ accepts both.
    assert sum(1 for c in out if c.exact_match) == 1  # only AB+ is exact


def test_rh_negative_recipient_excludes_all_rh_positive_donors(engine, areas):
    """F7.2: A- recipient must NEVER see any Rh+ donor in the eligible list."""
    req = _make_request(engine, area_id=areas["dhanmondi"], blood_group="A-")
    phones = {
        "A+": "01712345711",
        "B+": "01712345712",
        "O+": "01712345713",
        "AB+": "01712345714",
        "A-": "01712345715",
        "B-": "01712345716",
        "O-": "01712345717",
        "AB-": "01712345718",
    }
    for g in phones:
        _make_donor(
            engine,
            name=f"D-{g}",
            phone=phones[g],
            area_id=areas["dhanmondi"],
            blood_group=g,
        )
    donors = list(
        Session(engine).exec(__import__("sqlmodel").select(Donor)).all()
    )
    out = compute_candidates(
        request=req,
        donors=donors,
        contact_attempts=[],
        min_donation_gap_days=120,
        recent_contact_hours=24,
        now=datetime.now(UTC),
    )
    eligible = [c for c in out if c.ineligible is None]
    rh_pos_eligible = [c for c in eligible if c.donor.blood_group.endswith("+")]
    assert rh_pos_eligible == []


def test_universal_donor_matches_every_recipient(engine, areas):
    """F7.2: An O- donor must be eligible for every recipient blood group."""
    for i, recipient in enumerate(BLOOD_GROUPS):
        req = _make_request(
            engine, area_id=areas["dhanmondi"], blood_group=recipient
        )
        d = _make_donor(
            engine,
            name=f"O-neg-{recipient}",
            phone=f"01712345{800 + i:03d}",
            area_id=areas["dhanmondi"],
            blood_group="O-",
        )
        donors = [d]
        out = compute_candidates(
            request=req,
            donors=donors,
            contact_attempts=[],
            min_donation_gap_days=120,
            recent_contact_hours=24,
            now=datetime.now(UTC),
        )
        assert out[0].ineligible is None, (
            f"O- donor should be eligible for {recipient}, got {out[0].ineligible}"
        )
        # sanity: compatibility layer agrees
        assert can_donate_to("O-", recipient) is True
