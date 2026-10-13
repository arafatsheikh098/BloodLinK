"""Stats page tests (F9.1, F9.2, F9.3)."""
from __future__ import annotations

import pytest
from sqlmodel import Session

from app.models.area import Area
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.phone import normalize_bd_mobile
from app.stats import compute_stats
from app.tokens import hash_token, new_token


@pytest.fixture
def areas(engine):
    with Session(engine) as session:
        a1 = Area(name="Dhanmondi", is_active=True)
        a2 = Area(name="Mirpur", is_active=True)
        a3 = Area(name="Old", is_active=False)  # inactive
        session.add_all([a1, a2, a3])
        session.commit()
        session.refresh(a1)
        session.refresh(a2)
        session.refresh(a3)
    return {"dhanmondi": a1.id, "mirpur": a2.id, "old": a3.id}


def _make_donor(engine, *, name, phone, area_id, status=DonorStatus.VERIFIED.value):
    with Session(engine) as session:
        d = Donor(
            manage_token_hash=hash_token(new_token(24)),
            name=name,
            blood_group="A+",
            phone_normalized=normalize_bd_mobile(phone),
            area_id=area_id,
            is_over_18=True,
            consent_contact=True,
            consent_verify=True,
            status=status,
        )
        session.add(d)
        session.commit()


def test_stats_page_loads(app_client):
    r = app_client.get("/stats")
    assert r.status_code == 200
    assert "verified" in r.text.lower() or "donor" in r.text.lower()


def test_stats_excludes_unverified(engine, areas):
    _make_donor(
        engine,
        name="X",
        phone="01712345601",
        area_id=areas["dhanmondi"],
        status=DonorStatus.UNVERIFIED.value,
    )
    with Session(engine) as session:
        s = compute_stats(session)
    # No cells, total = 0
    assert s.total == 0


def test_stats_excludes_suspended(engine, areas):
    _make_donor(
        engine,
        name="X",
        phone="01712345602",
        area_id=areas["dhanmondi"],
        status=DonorStatus.SUSPENDED.value,
    )
    with Session(engine) as session:
        s = compute_stats(session)
    assert s.total == 0


def test_stats_counts_verified(engine, areas):
    for i in range(5):
        _make_donor(
            engine,
            name=f"X{i}",
            phone=f"017123456{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    with Session(engine) as session:
        s = compute_stats(session)
    assert s.total == 5
    cell = s.cells.get(("Dhanmondi", "A+"))
    assert cell is not None
    assert cell.count == 5
    assert cell.suppressed is False


def test_stats_suppresses_small_counts(engine, areas):
    """F9.2: counts < threshold render as 'fewer than N'."""
    for i in range(2):
        _make_donor(
            engine,
            name=f"X{i}",
            phone=f"017123457{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    with Session(engine) as session:
        s = compute_stats(session)
    cell = s.cells.get(("Dhanmondi", "A+"))
    assert cell is not None
    assert cell.suppressed is True


def test_stats_threshold_at_exact_count(engine, areas):
    """At exactly the threshold (default 3), the count is shown."""
    for i in range(3):
        _make_donor(
            engine,
            name=f"X{i}",
            phone=f"017123458{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    with Session(engine) as session:
        s = compute_stats(session)
    cell = s.cells.get(("Dhanmondi", "A+"))
    assert cell.count == 3
    assert cell.suppressed is False


def test_stats_threshold_boundary_2(engine, areas):
    for i in range(2):
        _make_donor(
            engine,
            name=f"X{i}",
            phone=f"017123459{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    with Session(engine) as session:
        s = compute_stats(session)
    cell = s.cells.get(("Dhanmondi", "A+"))
    assert cell.suppressed is True


def test_stats_threshold_boundary_4(engine, areas):
    for i in range(4):
        _make_donor(
            engine,
            name=f"X{i}",
            phone=f"017123450{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    with Session(engine) as session:
        s = compute_stats(session)
    cell = s.cells.get(("Dhanmondi", "A+"))
    assert cell.count == 4
    assert cell.suppressed is False


def test_stats_includes_all_blood_groups(engine, areas):
    with Session(engine) as session:
        s = compute_stats(session)
    # 8 blood groups always
    assert s.columns == list(BLOOD_GROUPS)
    assert len(s.columns) == 8


def test_stats_excludes_inactive_areas(engine, areas):
    _make_donor(
        engine, name="X", phone="01712346111", area_id=areas["old"]
    )
    with Session(engine) as session:
        s = compute_stats(session)
    # 'Old' is inactive — no rows for it
    for area_name in s.rows:
        assert area_name != "Old"


def test_stats_page_no_pii(app_client, engine, areas):
    for i in range(5):
        _make_donor(
            engine,
            name=f"SecretName{i}",
            phone=f"017123462{10 + i:02d}",
            area_id=areas["dhanmondi"],
        )
    r = app_client.get("/stats")
    assert r.status_code == 200
    assert "SecretName" not in r.text
    assert "01712346210" not in r.text
    assert "+880" not in r.text
