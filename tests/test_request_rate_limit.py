"""Request rate limit tests (F5.3, F5.4)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlmodel import Session

from app.models.area import Area
from app.models.request import BloodRequest, RequestStatus
from app.phone import normalize_bd_mobile
from app.rate_limit import (
    IP_MAX_PER_HOUR,
    PHONE_MAX_ACTIVE,
    active_requests_for_phone,
    hash_phone,
    is_ip_rate_limited,
    phone_has_room,
    recent_ip_count,
    record_attempt,
)
from app.tokens import new_token


@pytest.fixture
def area_id(engine):
    with Session(engine) as session:
        a = Area(name="Dhanmondi", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
        return a.id


def test_hash_phone_is_stable():
    assert hash_phone("+8801712345678") == hash_phone("+8801712345678")
    assert hash_phone("+8801712345678") != hash_phone("+8801812345678")


def test_recent_ip_count_starts_at_zero(engine):
    now = datetime.now(UTC)
    with Session(engine) as session:
        assert recent_ip_count(session, "1.2.3.4", now) == 0
        record_attempt(session, source_ip="1.2.3.4", requester_phone_hash=None, accepted=True, now=now)
        session.commit()
    with Session(engine) as session:
        assert recent_ip_count(session, "1.2.3.4", now) == 1


def test_recent_ip_count_ignores_other_ips(engine):
    now = datetime.now(UTC)
    with Session(engine) as session:
        record_attempt(session, source_ip="9.9.9.9", requester_phone_hash=None, accepted=True, now=now)
        session.commit()
    with Session(engine) as session:
        assert recent_ip_count(session, "1.2.3.4", now) == 0


def test_recent_ip_count_respects_window(engine):
    now = datetime.now(UTC)
    with Session(engine) as session:
        for _ in range(3):
            record_attempt(
                session,
                source_ip="1.2.3.4",
                requester_phone_hash=None,
                accepted=True,
                now=now - timedelta(hours=2),
            )
        session.commit()
    with Session(engine) as session:
        assert recent_ip_count(session, "1.2.3.4", now) == 0
        assert not is_ip_rate_limited(session, "1.2.3.4", now)


def test_is_ip_rate_limited_at_threshold(engine):
    now = datetime.now(UTC)
    with Session(engine) as session:
        for _ in range(IP_MAX_PER_HOUR):
            record_attempt(session, source_ip="5.5.5.5", requester_phone_hash=None, accepted=True, now=now)
        session.commit()
    with Session(engine) as session:
        assert recent_ip_count(session, "5.5.5.5", now) == IP_MAX_PER_HOUR
        assert is_ip_rate_limited(session, "5.5.5.5", now)


def test_active_requests_for_phone_counts_only_active(engine, area_id):
    phone = "+8801712345678"
    needed = datetime.now(UTC) + timedelta(hours=4)
    with Session(engine) as session:
        for _ in range(2):
            session.add(
                BloodRequest(
                    public_token=new_token(24),
                    blood_group="A+",
                    units=1,
                    hospital_name="H",
                    area_id=area_id,
                    needed_by=needed,
                    requester_name="R",
                    requester_phone_normalized=phone,
                    status=RequestStatus.PENDING.value,
                )
            )
        session.add(
            BloodRequest(
                public_token=new_token(24),
                blood_group="A+",
                units=1,
                hospital_name="H",
                area_id=area_id,
                needed_by=needed,
                requester_name="R",
                requester_phone_normalized=phone,
                status=RequestStatus.FULFILLED.value,
            )
        )
        session.commit()
    with Session(engine) as session:
        assert active_requests_for_phone(session, phone) == 2
        assert phone_has_room(session, phone) is True


def test_phone_has_room_blocks_at_cap(engine, area_id):
    phone = "+8801712345678"
    needed = datetime.now(UTC) + timedelta(hours=4)
    with Session(engine) as session:
        for _ in range(PHONE_MAX_ACTIVE):
            session.add(
                BloodRequest(
                    public_token=new_token(24),
                    blood_group="A+",
                    units=1,
                    hospital_name="H",
                    area_id=area_id,
                    needed_by=needed,
                    requester_name="R",
                    requester_phone_normalized=phone,
                    status=RequestStatus.PENDING.value,
                )
            )
        session.commit()
    with Session(engine) as session:
        assert active_requests_for_phone(session, phone) == PHONE_MAX_ACTIVE
        assert phone_has_room(session, phone) is False


def test_window_releases_ip(engine):
    """F5.3: after the window passes, the IP is no longer rate-limited."""
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base) as frozen:
        for _ in range(IP_MAX_PER_HOUR):
            with Session(engine) as session:
                record_attempt(session, source_ip="6.6.6.6", requester_phone_hash=None, accepted=True)
                session.commit()
        with Session(engine) as session:
            assert is_ip_rate_limited(session, "6.6.6.6", datetime.now(UTC))
        frozen.tick(delta=timedelta(hours=1, minutes=1))
        with Session(engine) as session:
            assert not is_ip_rate_limited(session, "6.6.6.6", datetime.now(UTC))


def test_normalize_phone_then_check():
    """F5.4 helper should work via the normalized form (the route normalizes
    first, so the count is by normalized value)."""
    raw = "01712345678"
    normalized = normalize_bd_mobile(raw)
    assert normalized == "+8801712345678"
