"""Custom error page tests (F11.6)."""
from __future__ import annotations


def test_404_renders_custom_page(app_client):
    r = app_client.get("/this-page-does-not-exist")
    assert r.status_code == 404
    # Custom page renders base layout
    assert "BloodLink" in r.text
    # 404 message text is present
    assert "404" in r.text or "not found" in r.text.lower()


def test_404_no_pii(app_client):
    r = app_client.get("/missing")
    assert r.status_code == 404
    assert "+880" not in r.text


def test_404_html_escaped(app_client):
    r = app_client.get("/<script>alert(1)</script>")
    # We don't even hit the route — Starlette returns 404 with the path
    # reflected in some form, but autoescape in Jinja is in effect.
    assert r.status_code in {404, 307}  # 307 if the path is normalized
    if r.status_code == 404:
        assert "<script>alert" not in r.text
