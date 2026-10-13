"""Idempotent seed test (F11.8)."""
from __future__ import annotations

from sqlmodel import Session, select

from app.db import get_engine
from app.models.area import Area
from app.models.donor import Donor
from app.models.request import BloodRequest
from app.seed import seed_demo


def test_seed_creates_data(app_client):
    seed_demo(get_engine())
    with Session(get_engine()) as session:
        areas = list(session.exec(select(Area)).all())
        donors = list(session.exec(select(Donor)).all())
        requests = list(session.exec(select(BloodRequest)).all())
    assert len(areas) >= 3
    assert len(donors) >= 24
    assert len(requests) >= 1


def test_seed_idempotent(app_client):
    seed_demo(get_engine())
    with Session(get_engine()) as session:
        donors_first = len(list(session.exec(select(Donor)).all()))
    seed_demo(get_engine())
    seed_demo(get_engine())
    with Session(get_engine()) as session:
        donors_second = len(list(session.exec(select(Donor)).all()))
    assert donors_first == donors_second


def test_seed_uses_fake_phones(app_client):
    seed_demo(get_engine())
    with Session(get_engine()) as session:
        for d in session.exec(select(Donor)).all():
            assert d.phone_normalized.startswith("+88017555")


def test_seed_donors_verified(app_client):
    seed_demo(get_engine())
    with Session(get_engine()) as session:
        for d in session.exec(select(Donor)).all():
            assert d.status == "verified"
