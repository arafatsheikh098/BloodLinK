"""Area management tests."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.models.area import Area
from app.models.coordinator import Coordinator
from app.security import hash_password


@pytest.fixture
def logged_in(app_client, engine):
    """Log in a coordinator and return the csrf for state-changing calls."""
    with Session(engine) as session:
        session.add(Coordinator(username="c1", password_hash=hash_password("x")))
        session.commit()
    r = app_client.get("/login")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    app_client.post(
        "/login",
        data={"username": "c1", "password": "x", "csrf_token": csrf},
    )
    return app_client


def test_areas_require_login(app_client):
    r = app_client.get("/areas")
    assert r.status_code == 401


def test_create_area(logged_in, engine):
    r = logged_in.get("/areas")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = logged_in.post("/areas", data={"name": "Uttara", "csrf_token": csrf})
    assert r.status_code == 303
    with Session(engine) as session:
        areas = list(session.exec(select(Area)).all())
    assert any(a.name == "Uttara" for a in areas)


def test_rename_area(logged_in, engine):
    with Session(engine) as session:
        a = Area(name="Old", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
    r = logged_in.get("/areas")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = logged_in.post(f"/areas/{a.id}/rename", data={"name": "New", "csrf_token": csrf})
    assert r.status_code == 303
    with Session(engine) as session:
        a2 = session.get(Area, a.id)
    assert a2.name == "New"


def test_deactivate_area(logged_in, engine):
    with Session(engine) as session:
        a = Area(name="Active", is_active=True)
        session.add(a)
        session.commit()
        session.refresh(a)
    r = logged_in.get("/areas")
    csrf = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            csrf = line.split('value="', 1)[1].split('"', 1)[0]
            break
    r = logged_in.post(f"/areas/{a.id}/deactivate", data={"csrf_token": csrf})
    assert r.status_code == 303
    with Session(engine) as session:
        a2 = session.get(Area, a.id)
    assert a2.is_active is False
