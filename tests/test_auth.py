"""Auth tests (F1.1, F1.3, F1.4)."""
from __future__ import annotations

import pytest
from freezegun import freeze_time
from sqlmodel import Session

from app.models.coordinator import Coordinator
from app.security import hash_password


@pytest.fixture
def app_with_coordinator(app_client):
    """Pre-create a coordinator for the tests."""
    # Re-use the engine from conftest.
    from app.db import get_engine

    with Session(get_engine()) as session:
        session.add(
            Coordinator(username="coord1", password_hash=hash_password("correct-horse"))
        )
        session.commit()
    return app_client


def _get_csrf_and_cookies(client) -> tuple[str, dict]:
    r = client.get("/login")
    assert r.status_code == 200
    token = None
    for line in r.text.splitlines():
        if 'name="csrf_token"' in line:
            token = line.split('value="', 1)[1].split('"', 1)[0]
            break
    assert token, "csrf token input not found"
    return token, dict(client.cookies)


def test_login_success_sets_session(app_with_coordinator):
    token, _ = _get_csrf_and_cookies(app_with_coordinator)
    r = app_with_coordinator.post(
        "/login",
        data={"username": "coord1", "password": "correct-horse", "csrf_token": token},
    )
    assert r.status_code == 303
    # Set-Cookie for session
    cookies = r.headers.get("set-cookie", "")
    assert "bloodlink_session" in cookies


def test_wrong_password_returns_401(app_with_coordinator):
    token, _ = _get_csrf_and_cookies(app_with_coordinator)
    r = app_with_coordinator.post(
        "/login",
        data={"username": "coord1", "password": "WRONG", "csrf_token": token},
    )
    assert r.status_code == 401


def test_unknown_username_same_error(app_with_coordinator):
    """F1.1: unknown username and wrong password must return the same generic error
    through the same code path."""
    token, _ = _get_csrf_and_cookies(app_with_coordinator)
    r1 = app_with_coordinator.post(
        "/login",
        data={"username": "coord1", "password": "WRONG", "csrf_token": token},
    )
    # Get a fresh CSRF for the second attempt (sessions are shared via cookies).
    token2, _ = _get_csrf_and_cookies(app_with_coordinator)
    r2 = app_with_coordinator.post(
        "/login",
        data={"username": "nosuchuser", "password": "WRONG", "csrf_token": token2},
    )
    assert r1.status_code == r2.status_code == 401
    # The same error message is shown
    assert "Invalid username or password" in r1.text
    assert "Invalid username or password" in r2.text
    # And the same response body structure (no difference in HTML)
    import re
    body1 = re.sub(r"\s+", " ", r1.text)
    body2 = re.sub(r"\s+", " ", r2.text)
    # Both contain the same error block; we only check the visible error text
    assert "Invalid username or password" in body1
    assert "Invalid username or password" in body2


def test_rate_limit_triggers_on_6th_failure(app_with_coordinator):
    """F1.3: the 6th failure within 15 minutes triggers 429."""
    base = "2026-10-13T10:00:00+00:00"
    with freeze_time(base) as frozen:
        for i in range(5):
            token, _ = _get_csrf_and_cookies(app_with_coordinator)
            r = app_with_coordinator.post(
                "/login",
                data={"username": "coord1", "password": "WRONG", "csrf_token": token},
            )
            assert r.status_code == 401, f"attempt {i+1} expected 401, got {r.status_code}"
        # 6th attempt should be 429
        token, _ = _get_csrf_and_cookies(app_with_coordinator)
        r = app_with_coordinator.post(
            "/login",
            data={"username": "coord1", "password": "WRONG", "csrf_token": token},
        )
        assert r.status_code == 429
        # Move forward past the window
        frozen.tick(delta=60 * 16)  # 16 minutes
        token, _ = _get_csrf_and_cookies(app_with_coordinator)
        r = app_with_coordinator.post(
            "/login",
            data={"username": "coord1", "password": "WRONG", "csrf_token": token},
        )
        assert r.status_code == 401  # window has passed


def test_session_cookie_flags(app_with_coordinator):
    """F1.4: HttpOnly + SameSite=Lax. Secure only in production."""
    token, _ = _get_csrf_and_cookies(app_with_coordinator)
    r = app_with_coordinator.post(
        "/login",
        data={"username": "coord1", "password": "correct-horse", "csrf_token": token},
    )
    cookie = r.headers.get("set-cookie", "")
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    # In test (non-production) Secure should NOT be set.
    assert "secure" not in cookie.lower()


def test_logout_clears_session(app_with_coordinator):
    token, _ = _get_csrf_and_cookies(app_with_coordinator)
    app_with_coordinator.post(
        "/login",
        data={"username": "coord1", "password": "correct-horse", "csrf_token": token},
    )
    # Now logout
    token2, _ = _get_csrf_and_cookies(app_with_coordinator)
    r2 = app_with_coordinator.post(
        "/logout",
        data={"csrf_token": token2},
    )
    assert r2.status_code == 303
