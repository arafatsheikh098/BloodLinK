"""Purge requester PII from closed requests (F11.2).

`purge_old_requests(retention_days)` removes requester_name and
requester_phone_normalized (and `note`) from any request whose
closed_at is older than `retention_days` days. Open requests are
untouched. The public_token, blood_group, hospital, area, etc. are kept
so historical aggregates still work.

We do NOT delete the row; we only null out the PII columns.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.audit import write_audit
from app.models.audit_log import AuditAction
from app.models.request import BloodRequest, RequestStatus

CLOSED_STATUSES = {
    RequestStatus.FULFILLED.value,
    RequestStatus.CANCELLED.value,
    RequestStatus.REJECTED.value,
    RequestStatus.EXPIRED.value,
}


def purge_old_requests(retention_days: int) -> int:
    """Null out PII columns for closed requests older than `retention_days`.

    Returns the number of rows touched.
    """
    from app.db import get_engine

    engine = get_engine()
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    touched = 0
    with Session(engine) as session:
        stmt = select(BloodRequest).where(BloodRequest.status.in_(list(CLOSED_STATUSES)))
        candidates = list(session.exec(stmt).all())
        for r in candidates:
            closed_at = r.closed_at or r.needed_by
            if closed_at is None:
                continue
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=UTC)
            if closed_at > cutoff:
                continue
            r.requester_name = ""
            r.requester_phone_normalized = ""
            r.note = None
            session.add(r)
            touched += 1
        write_audit(
            session,
            AuditAction.PURGE_RUN,
            actor_kind="system",
            detail=f"retention_days={retention_days};touched={touched}",
        )
        session.commit()
    return touched
