"""Audit log writer (F11.1).

Every coordinator action that changes state — verify, suspend, reveal phone,
contact attempt, status changes, deletions — MUST go through write_audit so
the audit log is complete and testable.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.models.audit_log import AuditAction, AuditLog

# PII patterns that must never appear in audit detail. We refuse to write
# rather than silently redact so a careless caller is loud, not quiet.
_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Bangladesh phone (E.164 +8801xxxxxxxxx, or 01xxxxxxxxx, or 8801xxxxxxxxx)
    re.compile(r"(\+?880|0)1[3-9]\d{8}"),
    # Generic 10+ digit run that could be a phone or chat id
    re.compile(r"\d{10,}"),
    # 32+ char hex (could be a token hash)
    re.compile(r"[0-9a-fA-F]{32,}"),
    # Telegram chat IDs are positive integers up to ~13 digits
    re.compile(r"chat_id=\d+"),
    # Anything that looks like an email
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
)


def write_audit(
    session: Session,
    action: AuditAction | str,
    *,
    actor_kind: str = "coordinator",
    coordinator_id: int | None = None,
    donor_id: int | None = None,
    request_id: int | None = None,
    contact_attempt_id: int | None = None,
    detail: str | None = None,
) -> AuditLog:
    """Insert an audit row. Commits nothing; the caller controls the transaction."""
    action_value = action.value if isinstance(action, AuditAction) else str(action)
    entry = AuditLog(
        action=action_value,
        actor_kind=actor_kind,
        coordinator_id=coordinator_id,
        donor_id=donor_id,
        request_id=request_id,
        contact_attempt_id=contact_attempt_id,
        detail=_safe_detail(detail),
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    session.flush()
    return entry


def _safe_detail(detail: Any) -> str | None:
    """Truncate detail to fit the column and refuse PII (F11.1).

    If the detail contains anything that looks like a phone number, a
    chat_id, a token hash, or an email address, we raise so the caller
    knows to fix the bug. Silently storing PII in the audit log would
    defeat the point of having a privacy-first audit trail.
    """
    if detail is None:
        return None
    s = str(detail)
    for pat in _PII_PATTERNS:
        if pat.search(s):
            raise ValueError(
                f"audit detail contains PII-like content (pattern={pat.pattern!r}); "
                "do not pass phone, chat_id, token hash, or email to write_audit"
            )
    if len(s) > 500:
        # Truncating would let a long PII-containing string sneak through the
        # regex check after a quiet chop. Force the caller to shorten.
        raise ValueError(
            f"audit detail too long ({len(s)} > 500 chars); shorten the message"
        )
    return s
