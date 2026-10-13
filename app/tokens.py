"""Secure random tokens + hashing helpers.

Used for donor manage links and request tracking links. Tokens are at least
128 bits of entropy (16 bytes / 32 hex chars / 22 base64url chars). They are
stored only as a hash; the plaintext is shown to the user once at creation.
"""
from __future__ import annotations

import hashlib
import secrets


def new_token(nbytes: int = 24) -> str:
    """Return a URL-safe random token with `nbytes` bytes of entropy (default 192 bits)."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Return a stable hash of a token. We use SHA-256 hex for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
