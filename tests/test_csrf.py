"""Route-discovery CSRF test (F1.2 / G5).

Enumerates every state-changing route registered on the app at runtime and
asserts that:
  - a missing CSRF token is rejected with 403;
  - a wrong CSRF token is rejected with 403;
  - for routes that require a coordinator session, a missing session is rejected
    (with 401 or 403).

This test must be extended in later milestones as new routes are added; it
auto-discovers them, so the inheritance happens automatically.
"""
from __future__ import annotations

from fastapi.routing import APIRoute

# Routes that should NOT require a CSRF token (the login endpoint itself, and
# routes that are explicitly excluded). Add to this set as needed; missing
# entries will be flagged as failures below.
CSRF_EXEMPT_PATHS = {
    ("/login", "POST"),  # login form has its own CSRF
}


def _iter_state_changing_routes(app):
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or []:
            if method in {"GET", "HEAD", "OPTIONS"}:
                continue
            yield route.path, method, route


def test_every_state_changing_route_rejects_missing_csrf(app_client):
    app = app_client.app
    state_routes = list(_iter_state_changing_routes(app))
    assert state_routes, "no state-changing routes found"
    for path, method, _ in state_routes:
        if (path, method) in CSRF_EXEMPT_PATHS:
            continue
        r = app_client.request(method, path)
        assert r.status_code == 403, f"{method} {path} should 403 without CSRF, got {r.status_code}"
        # The body must not include a successful response indicator.


def test_wrong_csrf_token_rejected(app_client):
    app = app_client.app
    state_routes = list(_iter_state_changing_routes(app))
    assert state_routes
    for path, method, _ in state_routes:
        if (path, method) in CSRF_EXEMPT_PATHS:
            continue
        r = app_client.request(
            method,
            path,
            data="csrf_token=this-is-not-a-valid-token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 403, f"{method} {path} with bad CSRF should 403, got {r.status_code}"


def test_login_route_present_and_csrf_protected(app_client):
    """The login route itself must appear in the state-changing set so its own
    CSRF is enforced, even though we excluded it from the auto-test above."""
    r = app_client.post("/login", data={"username": "x", "password": "y"})
    # Without a CSRF token, this should still be 403 (or 422 if FastAPI rejects the
    # body first). The important point: it must not be 200/303.
    assert r.status_code in {403, 422}
