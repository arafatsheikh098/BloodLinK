"""Coordinator matching (F7).

  GET  /coordinator/matching/{rid}                        — candidate list page
  POST /coordinator/matching/{rid}/contact                — record a contact attempt
  POST /coordinator/matching/{rid}/contact/{aid}/donated  — mark donated (closes the request)

The pure ranking lives in `app.matching.compute_candidates`. Here we wire the
ranked list to the database, render it with masked phones, and let the
coordinator record contact attempts per donor.

Notes:
  - Only verified requests reach this page (F6.2 / F7.6 precondition).
  - Phones are masked. The coordinator can reveal a phone on the donor page.
  - Recording 'donated' closes the request to 'fulfilled' (F7.6).
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.config import get_settings
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import RequireCoordinator, flash, pop_flashes
from app.matching import can_match, compute_candidates
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.contact_attempt import ContactAttempt, ContactOutcome
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.request import BloodRequest, RequestStatus
from app.phone import mask_phone
from app.request_validation import effective_status
from app.templates import make_templates, render_lang_from_request

router = APIRouter(prefix="/coordinator/matching")
templates = make_templates()

# Outcomes exposed to the form (F7.6). 'donated' is a separate endpoint so it
# can also update donor.last_donation_date and close the request.
FORM_OUTCOMES: tuple[str, ...] = (
    ContactOutcome.CONTACTED.value,
    ContactOutcome.ACCEPTED.value,
    ContactOutcome.DECLINED.value,
    ContactOutcome.NO_ANSWER.value,
)


def _all_areas(session: Session) -> list[Area]:
    return list(session.exec(select(Area).order_by(Area.name)).all())


def _load_request_or_404(session: Session, rid: int) -> BloodRequest:
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    return req


def _build_candidates(session: Session, request: BloodRequest, now: datetime):
    """Load donors and contact attempts, run the pure matching function."""
    settings = get_settings()
    donors = list(
        session.exec(
            select(Donor).where(Donor.status != DonorStatus.UNVERIFIED.value)
        ).all()
    )
    attempts = list(
        session.exec(
            select(ContactAttempt).where(ContactAttempt.request_id == request.id)
        ).all()
    )
    return compute_candidates(
        request=request,
        donors=donors,
        contact_attempts=attempts,
        min_donation_gap_days=settings.min_donation_gap_days,
        recent_contact_hours=settings.recent_contact_hours,
        now=now,
    )


# --- CANDIDATE LIST ----------------------------------------------------------


@router.get("/{rid}", response_class=HTMLResponse)
def candidates(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
) -> HTMLResponse:
    req = _load_request_or_404(session, rid)
    now = datetime.now(UTC)
    effective = effective_status(req.status, req.needed_by, now=now)
    if not can_match(req, now=now):
        flash(
            request,
            "error",
            "Only verified and not-yet-expired requests can be matched.",
        )
        return RedirectResponse(
            url=f"/coordinator/requests/{rid}", status_code=303
        )

    candidates_list = _build_candidates(session, req, now)
    area = session.get(Area, req.area_id) if req.area_id else None

    # Lookup existing attempts for display
    attempts_rows = list(
        session.exec(
            select(ContactAttempt)
            .where(ContactAttempt.request_id == req.id)
            .order_by(ContactAttempt.created_at.desc())
        ).all()
    )
    by_donor: dict[int, list[ContactAttempt]] = {}
    for a in attempts_rows:
        by_donor.setdefault(a.donor_id, []).append(a)

    return templates.TemplateResponse(
        request,
        "coordinator/matching/candidates.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "request_obj": req,
            "request_effective": effective,
            "area": area,
            "candidates": candidates_list,
            "by_donor": by_donor,
            "areas": _all_areas(session),
            "blood_groups": BLOOD_GROUPS,
            "outcomes": FORM_OUTCOMES,
            "mask_phone": mask_phone,
            "settings": get_settings(),
            "today_iso": date.today().isoformat(),
        },
    )


# --- RECORD CONTACT ATTEMPT --------------------------------------------------


@router.post("/{rid}/contact", dependencies=[CsrfDep])
def record_contact(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    donor_id: int = Form(...),
    outcome: str = Form(...),
    note: str = Form(default=""),
) -> RedirectResponse:
    req = _load_request_or_404(session, rid)
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    if outcome not in {o.value for o in ContactOutcome}:
        flash(request, "error", "Invalid contact outcome.")
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )
    if outcome == ContactOutcome.DONATED.value:
        # 'donated' must go through the dedicated endpoint so the donor's
        # last_donation_date is updated and the request is closed properly.
        flash(
            request,
            "error",
            "Please use the 'Mark as donated' action for the 'donated' outcome.",
        )
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )

    attempt = ContactAttempt(
        donor_id=donor.id,
        request_id=req.id,
        coordinator_id=current.id,
        outcome=outcome,
        note=(note or "").strip()[:500] or None,
    )
    session.add(attempt)
    session.flush()
    write_audit(
        session,
        AuditAction.CONTACT_ATTEMPT,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
        request_id=req.id,
        contact_attempt_id=attempt.id,
        detail=outcome,
    )
    session.commit()
    flash(request, "success", "Contact attempt recorded.")
    return RedirectResponse(url=f"/coordinator/matching/{rid}", status_code=303)


# --- MARK DONATED (closes request, updates donor last_donation_date) ---------


def _parse_donation_date(raw: str, request: Request, rid: int) -> date | None:
    """Parse a donation date string. On failure, flash and return None."""
    if not raw.strip():
        return date.today()
    try:
        d = date.fromisoformat(raw.strip())
    except ValueError:
        flash(request, "error", "Please enter a valid donation date.")
        return None
    if d > date.today():
        flash(request, "error", "Donation date cannot be in the future.")
        return None
    return d


@router.post("/{rid}/contact/{aid}/donated", dependencies=[CsrfDep])
def mark_donated_existing(
    rid: int,
    aid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    donation_date: str = Form(default=""),
    note: str = Form(default=""),
) -> RedirectResponse:
    """Mark an existing contact attempt as 'donated'."""
    req = _load_request_or_404(session, rid)
    attempt = session.get(ContactAttempt, aid)
    if not attempt or attempt.request_id != req.id:
        raise HTTPException(status_code=404, detail="contact attempt not found")
    donor = session.get(Donor, attempt.donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    d = _parse_donation_date(donation_date, request, rid)
    if d is None:
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )
    return _commit_donated(
        session=session,
        request=request,
        req=req,
        donor=donor,
        attempt=attempt,
        donation_date=d,
        note=note,
        current=current,
        rid=rid,
    )


@router.post("/{rid}/donated", dependencies=[CsrfDep])
def mark_donated_new(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    donor_id: int = Form(...),
    donation_date: str = Form(default=""),
    note: str = Form(default=""),
) -> RedirectResponse:
    """Create a 'donated' contact attempt from a donor id (no prior attempt)."""
    req = _load_request_or_404(session, rid)
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    d = _parse_donation_date(donation_date, request, rid)
    if d is None:
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )
    attempt = ContactAttempt(
        donor_id=donor.id,
        request_id=req.id,
        coordinator_id=current.id,
        outcome=ContactOutcome.CONTACTED.value,
        note=(note or "").strip()[:500] or None,
    )
    session.add(attempt)
    session.flush()
    return _commit_donated(
        session=session,
        request=request,
        req=req,
        donor=donor,
        attempt=attempt,
        donation_date=d,
        note=note,
        current=current,
        rid=rid,
    )


def _commit_donated(
    *,
    session: Session,
    request: Request,
    req: BloodRequest,
    donor: Donor,
    attempt: ContactAttempt,
    donation_date: date,
    note: str,
    current,
    rid: int,
) -> RedirectResponse:
    # Idempotency / race guard (H3): a second coordinator clicking
    # "donated" on the same request — or a double-click — must not
    # re-overwrite last_donation_date, add a second "donated" audit row,
    # or re-close the request. The check is done inside the same
    # transaction so it is safe under concurrent submissions.
    if req.status not in (
        RequestStatus.VERIFIED.value,
        RequestStatus.PENDING.value,
    ):
        flash(
            request,
            "error",
            f"Request is already {req.status}; donation not recorded again.",
        )
        return RedirectResponse(
            url=f"/coordinator/requests/{rid}", status_code=303
        )
    if attempt.outcome == ContactOutcome.DONATED.value:
        flash(request, "error", "This attempt is already recorded as donated.")
        return RedirectResponse(
            url=f"/coordinator/requests/{rid}", status_code=303
        )
    if attempt.outcome == ContactOutcome.DECLINED.value:
        # F8.6: a donor who declined should not silently be flipped to
        # donated. Refuse and require the coordinator to add a fresh
        # contact attempt instead.
        flash(
            request,
            "error",
            "Cannot mark a declined attempt as donated. "
            "Use the 'other donor' flow to record a new attempt.",
        )
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )
    donor.last_donation_date = donation_date
    donor.updated_at = datetime.now(UTC)
    attempt.outcome = ContactOutcome.DONATED.value
    if note.strip():
        attempt.note = (note or "").strip()[:500]
    req.status = RequestStatus.FULFILLED.value
    req.closed_at = datetime.now(UTC)
    req.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.CONTACT_ATTEMPT,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
        request_id=req.id,
        contact_attempt_id=attempt.id,
        detail=f"donated;date={donation_date.isoformat()}",
    )
    session.commit()
    flash(request, "success", "Donor marked as donated; request fulfilled.")
    return RedirectResponse(
        url=f"/coordinator/requests/{rid}", status_code=303
    )
