"""Signed callback data for Telegram inline keyboards (F8.5, F8.6).

We use itsdangerous to sign short JSON payloads with an expiry. Tampered or
expired payloads raise BadSignature or SignatureExpired; callers must treat
those as no-ops.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

CALLBACK_TTL_SECONDS = 60 * 60  # 1 hour


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt="tg-cb-v1")


def sign_callback(payload: dict[str, Any]) -> str:
    """Return a signed token for a small JSON payload."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return _serializer().dumps(raw)


def verify_callback(token: str) -> dict[str, Any] | None:
    """Return the payload dict, or None if tampered/expired/invalid."""
    try:
        raw = _serializer().loads(token, max_age=CALLBACK_TTL_SECONDS)
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def make_accept_token(request_id: int, donor_id: int, attempt_id: int) -> str:
    return sign_callback({"v": "accept", "r": request_id, "d": donor_id, "a": attempt_id})


def make_decline_token(request_id: int, donor_id: int, attempt_id: int) -> str:
    return sign_callback({"v": "decline", "r": request_id, "d": donor_id, "a": attempt_id})


def _now() -> datetime:
    return datetime.now(UTC)


def is_expired_iso(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < _now()
