"""Matching engine (F7).

Pure function: given a request, a list of donors, a settings object and a
reference time, return a ranked list of candidate donors with reasons.

We keep this a pure function so it is trivial to test exhaustively. The
route layer (coordinator_matching) wraps it with database lookups and
template rendering.

Output schema — list of dicts (one per candidate):

  {
    "donor": Donor,
    "exact_match": bool,        # same blood group as the request
    "same_area": bool,          # same area_id
    "days_since_donation": int | None,  # days since last donation (None if never)
    "recently_contacted": bool, # contacted for THIS request in the last 24h
    "ineligible": str | None,   # if not eligible, the reason
    "rank_score": tuple,        # used for sort stability
  }

Exclusion rules (F7.3):
  - unverified status
  - suspended status
  - not is_available
  - incompatible group (can_donate_to returns False)
  - ineligible by gap: last_donation_date within MIN_DONATION_GAP_DAYS

Rh- property (F7.2): an Rh- request never produces an Rh+ candidate. This is
already enforced by can_donate_to.

Ranking (F7.8):
  1. exact blood group match first
  2. same area_id next
  3. longest time since last donation
  4. donor id for stable order
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.compatibility import can_donate_to
from app.models.contact_attempt import ContactAttempt
from app.models.donor import Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus


@dataclass
class Candidate:
    donor: Donor
    exact_match: bool
    same_area: bool
    days_since_donation: int | None
    recently_contacted: bool
    ineligible: str | None
    rank_score: tuple


def _days_since(d: date | None, now: date) -> int | None:
    if d is None:
        return None
    return (now - d).days


def _recently_contacted(
    attempts: Iterable[ContactAttempt], donor_id: int, now: datetime, hours: int
) -> bool:
    cutoff = now - timedelta(hours=hours)
    for a in attempts:
        if a.donor_id != donor_id:
            continue
        # A failed send (no_answer) does NOT count as having reached the
        # donor. Otherwise the matching engine silently biases itself
        # against donors whose Telegram send failed.
        if a.outcome == "no_answer":
            continue
        ts = a.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= cutoff:
            return True
    return False


def compute_candidates(
    request: BloodRequest,
    donors: list[Donor],
    contact_attempts: list[ContactAttempt],
    min_donation_gap_days: int,
    recent_contact_hours: int,
    now: datetime,
) -> list[Candidate]:
    """Return ranked candidates. Excludes ineligible donors."""
    today = now.date()
    candidates: list[Candidate] = []

    for d in donors:
        # Eligibility
        days: int | None = None
        if d.status == DonorStatus.SUSPENDED.value:
            reason = "suspended"
        elif d.status == DonorStatus.UNVERIFIED.value:
            reason = "unverified"
        elif not d.is_available:
            reason = "unavailable"
        elif not can_donate_to(d.blood_group, request.blood_group):
            reason = "incompatible"
        else:
            days = _days_since(d.last_donation_date, today)
            if days is not None and days < min_donation_gap_days:
                reason = f"ineligible_gap({days}d<{min_donation_gap_days}d)"
            else:
                reason = None

        # F7.5 flag
        recent = _recently_contacted(contact_attempts, d.id, now, recent_contact_hours)

        exact = d.blood_group == request.blood_group
        same_area = d.area_id == request.area_id

        # Sort key: ineligible candidates go last.
        # We rank by:
        #   - eligibility (eligible first)
        #   - exact_match (True first)
        #   - same_area (True first)
        #   - days_since_donation (None = never donated, treated as +inf for "longest")
        #   - donor id (stable)
        # We encode "longest time since last donation" by sorting the NEGATIVE
        # of days (None -> 0 which is smaller than any real value). Actually we
        # want longest time -> first. So we use the tuple (-days, donor_id).
        if days is None:
            # Never donated: extremely long. Encode as a very large number.
            days_key = 10**9
        else:
            days_key = days
        rank = (
            1 if reason else 0,  # eligible first
            0 if exact else 1,
            0 if same_area else 1,
            -days_key,            # larger days = earlier
            d.id,                 # stable tiebreaker
        )
        candidates.append(
            Candidate(
                donor=d,
                exact_match=exact,
                same_area=same_area,
                days_since_donation=days,
                recently_contacted=recent,
                ineligible=reason,
                rank_score=rank,
            )
        )

    candidates.sort(key=lambda c: c.rank_score)
    return candidates


def can_match(request: BloodRequest, now: datetime | None = None) -> bool:
    """F6.2: only verified requests can be matched.

    A request whose needed_by has passed is considered expired.
    """
    now = now or datetime.now(UTC)
    if request.status == RequestStatus.VERIFIED.value:
        nb = request.needed_by
        if nb.tzinfo is None:
            nb = nb.replace(tzinfo=UTC)
        if nb >= now:
            return True
    return False
