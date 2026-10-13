"""CSRF protection for state-changing routes (F1 / G5).

A CSRF token is bound to the session and validated on every POST/PUT/PATCH/DELETE
request. Tokens are generated using itsdangerous so they are signed.
"""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.datastructures import FormData

from app.config import get_settings

CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "x-csrf-token"
_SESSION_KEY = "_csrf_secret"


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(get_settings().secret_key, salt="csrf-v1")


def get_or_create_csrf(request: Request) -> str:
    """Return a CSRF token, creating one in the session if missing."""
    secret = request.session.get(_SESSION_KEY)
    if not secret:
        secret = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = secret
    return _serializer().dumps(secret)


def verify_csrf(request: Request, submitted: str | None) -> None:
    """Raise 403 if the submitted CSRF token does not match the session token."""
    secret = request.session.get(_SESSION_KEY)
    if not secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf")
    if not submitted:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf")
    try:
        got = _serializer().loads(submitted)
    except BadSignature:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf") from None
    if not secrets.compare_digest(got, secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="csrf")


async def csrf_dependency(request: Request) -> None:
    """FastAPI dependency that blocks state-changing requests without a valid CSRF token.

    The token may be supplied either via the X-CSRF-Token header or as a form field.
    For non-form (e.g. JSON) requests the header is required.
    """
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    submitted: str | None = request.headers.get(CSRF_HEADER)
    if not submitted:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            # Parse once, cache on request.state.form so route handlers can re-use it.
            if not hasattr(request.state, "form"):
                try:
                    form: FormData = await request.form()
                    request.state.form = form
                except Exception:
                    request.state.form = None
            form = getattr(request.state, "form", None)
            if form is not None:
                value = form.get(CSRF_FORM_FIELD)
                if isinstance(value, str):
                    submitted = value
    verify_csrf(request, submitted)


CsrfDep = Depends(csrf_dependency)