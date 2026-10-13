"""Health check test (F11.3)."""
from __future__ import annotations


def test_health_returns_200(app_client):
    r = app_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
