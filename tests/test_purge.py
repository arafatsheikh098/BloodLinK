"""Purge tests (F11.2)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time
from sqlmodel import Session, select

from app.db import get_engine
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.request import BloodRequest, RequestStatus
from app.purge import purge_old_requests
from app.tokens import new_token


@pytest.fixture
def area_id(app_client):
    engine = get_engine()
    with Session(engine) as session:
        a = Area(name="Dhanmondi", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
    return a.id


def _make_request(
    app_client,
    area_id: int,
    *,
    status: str = RequestStatus.FULFILLED.value,
    closed_at: datetime | None = None,
    needed_by: datetime | None = None,
) -> BloodRequest:
    engine = get_engine()
    nb = needed_by or (datetime.now(UTC) + timedelta(hours=6))
    with Session(engine) as session:
        r = BloodRequest(
            public_token=new_token(24),
            blood_group="A+",
            units=1,
            hospital_name="H",
            area_id=area_id,
            needed_by=nb,
            requester_name="Original Name",
            requester_phone_normalized="+8801712345678",
            note="private note",
            status=status,
            closed_at=closed_at,
        )
        session.add(r)
        session.commit()
        session.refresh(r)
    return r


def test_purge_removes_old_closed_requests(app_client, area_id):
    old = _make_request(
        app_client,
        area_id=area_id,
        closed_at=datetime.now(UTC) - timedelta(days=100),
    )
    purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        r = session.get(BloodRequest, old.id)
    assert r.requester_name == ""
    assert r.requester_phone_normalized == ""
    assert r.note is None


def test_purge_keeps_recent_closed_requests(app_client, area_id):
    recent = _make_request(
        app_client,
        area_id=area_id,
        closed_at=datetime.now(UTC) - timedelta(days=5),
    )
    purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        r = session.get(BloodRequest, recent.id)
    assert r.requester_name == "Original Name"
    assert r.requester_phone_normalized == "+8801712345678"


def test_purge_keeps_open_requests(app_client, area_id):
    open_req = _make_request(
        app_client,
        area_id=area_id,
        status=RequestStatus.VERIFIED.value,
        closed_at=None,
        needed_by=datetime.now(UTC) + timedelta(days=10),
    )
    purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        r = session.get(BloodRequest, open_req.id)
    assert r.requester_name == "Original Name"


def test_purge_uses_needed_by_for_expired(app_client, area_id):
    r = _make_request(
        app_client,
        area_id=area_id,
        status=RequestStatus.EXPIRED.value,
        closed_at=None,
        needed_by=datetime.now(UTC) - timedelta(days=100),
    )
    purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        r2 = session.get(BloodRequest, r.id)
    assert r2.requester_name == ""


def test_purge_audit_row(app_client, area_id):
    _make_request(
        app_client,
        area_id=area_id,
        closed_at=datetime.now(UTC) - timedelta(days=100),
    )
    purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        from app.models.audit_log import AuditLog

        audits = list(
            session.exec(
                select(AuditLog).where(AuditLog.action == AuditAction.PURGE_RUN.value)
            ).all()
        )
    assert len(audits) == 1
    assert "touched=1" in (audits[0].detail or "")


def test_purge_returns_count(app_client, area_id):
    for _i in range(3):
        _make_request(
            app_client,
            area_id=area_id,
            closed_at=datetime.now(UTC) - timedelta(days=100),
        )
    n = purge_old_requests(retention_days=30)
    assert n == 3


def test_purge_with_freezegun(app_client, area_id):
    """Freezegun: at the boundary the request is still kept (closed_at == cutoff)."""
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base):
        r = _make_request(
            app_client,
            area_id=area_id,
            closed_at=datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC),
        )
    # 30 days retention at base 2026-10-13 → cutoff = 2026-09-13 10:00:00
    # closed_at == cutoff → not strictly older → keep
    n = purge_old_requests(retention_days=30)
    with Session(get_engine()) as session:
        r2 = session.get(BloodRequest, r.id)
    assert r2.requester_name == "Original Name"
    assert n == 0
