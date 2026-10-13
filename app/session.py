"""Session middleware (F1.4: HttpOnly, SameSite=Lax, Secure in production).

Uses Starlette's built-in SessionMiddleware (signed cookie with itsdangerous).
The signed secret is derived from our SECRET_KEY.
"""
from __future__ import annotations

from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings

SESSION_COOKIE = "bloodlink_session"


def add_session_middleware(app) -> None:
    settings = get_settings()
    # 32-byte random key is recommended; we derive from SECRET_KEY for reproducibility.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=SESSION_COOKIE,
        max_age=60 * 60 * 12,  # 12 hours
        same_site="lax",
        https_only=settings.is_production,
    )
