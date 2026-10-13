"""Audit log writer (F11.1).

Every coordinator action that changes state — verify, suspend, reveal phone,
contact attempt, status changes, deletions — MUST go through write_audit so
the audit log is complete and testable.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.models.audit_log import AuditAction, AuditLog


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
    """Truncate detail to fit the column. Must never contain PII (F11.1)."""
    if detail is None:
        return None
    s = str(detail)
    if len(s) > 500:
        s = s[:500]
    return s
