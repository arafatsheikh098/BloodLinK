"""Security header tests (F11.4)."""
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
