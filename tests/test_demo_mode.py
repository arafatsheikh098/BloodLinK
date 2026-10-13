"""DEMO_MODE tests (F11.7)."""
from __future__ import annotations

from app.config import get_settings


def test_demo_mode_banner_visible(monkeypatch, app_client):
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    r = app_client.get("/")
    assert r.status_code == 200
    assert "DEMO MODE" in r.text or "Demo" in r.text


def test_demo_mode_disabled_no_banner(monkeypatch, app_client):
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    r = app_client.get("/")
    assert r.status_code == 200
    assert "DEMO MODE" not in r.text


def test_demo_mode_disables_telegram_send(monkeypatch):
    from app.telegram import send_message

    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    get_settings.cache_clear()
    ok, err = send_message("any", "x")
    assert ok is False
    assert err == "disabled"


def test_seed_demo_refuses_without_demo_mode(monkeypatch):
    """Running `seed_demo` against a real deployment would create donors
    and requests with no visible marker that they are fake. The function
    must refuse unless DEMO_MODE=true.
    """
    import pytest

    from app.seed import seed_demo

    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="DEMO_MODE is not set"):
        seed_demo()
