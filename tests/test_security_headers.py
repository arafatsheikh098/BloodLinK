"""Security header tests (F11.4) and body-size limit (H)."""
from __future__ import annotations


def test_csp_no_unsafe_inline(app_client):
    r = app_client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert csp
    assert "'unsafe-inline'" not in csp
    assert "script-src 'self'" in csp


def test_x_content_type_options(app_client):
    r = app_client.get("/")
    assert r.headers.get("x-content-type-options") == "nosniff"


def test_referrer_policy(app_client):
    r = app_client.get("/")
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_frame_ancestors_none(app_client):
    r = app_client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "frame-ancestors 'none'" in csp


def test_x_frame_options(app_client):
    r = app_client.get("/")
    assert r.headers.get("x-frame-options") == "DENY"


def test_headers_on_404(app_client):
    r = app_client.get("/this-does-not-exist")
    assert r.status_code == 404
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_permissions_policy_set(app_client):
    r = app_client.get("/")
    pp = r.headers.get("permissions-policy", "")
    assert pp
    assert "geolocation=()" in pp
    assert "camera=()" in pp


def test_hsts_not_on_http(app_client):
    r = app_client.get("/")
    # Test client is http; HSTS only fires on https.
    assert r.headers.get("strict-transport-security") is None


def test_body_size_cap_rejects_oversized(app_client):
    """H: a 2 MiB body to a form endpoint must be rejected with 413."""
    big = b"x" * (2 * 1024 * 1024)
    r = app_client.post(
        "/request",
        content=big,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413


def test_body_size_cap_allows_normal(app_client):
    """A small body is NOT blocked by the size guard."""
    r = app_client.post(
        "/request",
        data={"x": "y"},
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    # It can be 400 (invalid form) or 200, but not 413.
    assert r.status_code != 413
