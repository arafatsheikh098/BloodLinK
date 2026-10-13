"""Per-IP and per-phone request rate limiting (F5.3, F5.4).

Limits are enforced by counting `RequestAttempt` rows:

  * Per IP (F5.3): at most 5 attempts in any 1-hour window. The 6th
    submission is rejected with 429.
  * Per phone (F5.4): a single phone cannot have more than 3 active
    requests (active = pending or verified). The 4th is rejected with
    400 ("too many active requests").

We use the same pattern as the login rate limit (count rows, no separate
counter table) so this works the same on SQLite and Postgres.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from app.models.request import ACTIVE_STATUSES, BloodRequest
from app.models.request_attempt import RequestAttempt

# F5.3
IP_MAX_PER_HOUR = 5
IP_WINDOW = timedelta(hours=1)
# F5.4
PHONE_MAX_ACTIVE = 3


def hash_phone(normalized_phone: str) -> str:
    """Stable hash for per-phone counting without storing the plaintext."""
    return hashlib.sha256(normalized_phone.encode("utf-8")).hexdigest()


def recent_ip_count(session: Session, ip: str, now: datetime) -> int:
    if not ip:
        return 0
    cutoff = now - IP_WINDOW
    stmt = select(RequestAttempt).where(
        RequestAttempt.source_ip == ip,
        RequestAttempt.created_at >= cutoff,
    )
    return len(session.exec(stmt).all())


def is_ip_rate_limited(session: Session, ip: str, now: datetime) -> bool:
    return recent_ip_count(session, ip, now) >= IP_MAX_PER_HOUR


def active_requests_for_phone(session: Session, normalized_phone: str) -> int:
    """Count BloodRequest rows with this phone in an active status."""
    stmt = select(BloodRequest).where(
        BloodRequest.requester_phone_normalized == normalized_phone,
        BloodRequest.status.in_(ACTIVE_STATUSES),
    )
    return len(session.exec(stmt).all())


def phone_has_room(session: Session, normalized_phone: str) -> bool:
    return active_requests_for_phone(session, normalized_phone) < PHONE_MAX_ACTIVE


def record_attempt(
    session: Session,
    *,
    source_ip: str | None,
    requester_phone_hash: str | None,
    accepted: bool,
    request_id: int | None = None,
    now: datetime | None = None,
) -> RequestAttempt:
    """Insert a RequestAttempt row. Caller controls the transaction."""
    now = now or datetime.now(UTC)
    row = RequestAttempt(
        source_ip=source_ip or None,
        requester_phone_hash=requester_phone_hash or None,
        accepted=accepted,
        request_id=request_id,
        created_at=now,
    )
    session.add(row)
    session.flush()
    return row
