"""Coordinator donor management (F4).

Endpoints:
  GET  /coordinator/donors                  — list + search + filter + paginate
  GET  /coordinator/donors/{donor_id}       — detail (masked phone, action forms)
  POST /coordinator/donors/{donor_id}/verify     — mark verified (optional note)
  POST /coordinator/donors/{donor_id}/suspend    — mark suspended
  POST /coordinator/donors/{donor_id}/unsuspend  — clear suspended (back to verified)
  POST /coordinator/donors/{donor_id}/regenerate-link — new manage link (old stops)
  POST /coordinator/donors/{donor_id}/record-donation — update last_donation_date
  POST /coordinator/donors/{donor_id}/reveal-phone   — full phone + audit row
  POST /coordinator/donors/{donor_id}/reveal-phone/clear — hide phone again

All endpoints require an active coordinator session. Phones are masked by
default; revealing writes exactly one audit row.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, or_, select

from app.audit import write_audit
from app.config import get_settings
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import RequireCoordinator, flash, pop_flashes
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.contact_attempt import ContactAttempt
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.request import BloodRequest
from app.phone import mask_phone
from app.templates import make_templates, render_lang_from_request
from app.tokens import hash_token, new_token

router = APIRouter(prefix="/coordinator/donors")
templates = make_templates()

PAGE_SIZE = 25
NOTE_MAX_LENGTH = 500
REVEAL_TTL_SECONDS = 600


def _all_areas(session: Session) -> list[Area]:
    return list(session.exec(select(Area).order_by(Area.name)).all())


def _is_revealed(request: Request, donor_id: int) -> bool:
    revealed = request.session.get("_revealed_phones", {})
    expires_at = revealed.get(str(donor_id))
    if not expires_at:
        return False
    try:
        ts = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if ts.tzinfo is None:
        # treat as UTC
        ts = ts.replace(tzinfo=UTC)
    if datetime.now(UTC) > ts:
        revealed.pop(str(donor_id), None)
        request.session["_revealed_phones"] = revealed
        return False
    return True


def _mark_revealed(request: Request, donor_id: int) -> None:
    from datetime import timedelta

    revealed = request.session.get("_revealed_phones", {})
    expires_at = datetime.now(UTC) + timedelta(seconds=REVEAL_TTL_SECONDS)
    revealed[str(donor_id)] = expires_at.isoformat()
    request.session["_revealed_phones"] = revealed


def _clear_revealed(request: Request, donor_id: int) -> None:
    revealed = request.session.get("_revealed_phones", {})
    revealed.pop(str(donor_id), None)
    request.session["_revealed_phones"] = revealed


def _pop_new_manage_link(request: Request, donor_id: int) -> str | None:
    bucket = request.session.get("_new_manage_links", {})
    plain = bucket.pop(str(donor_id), None)
    request.session["_new_manage_links"] = bucket
    return plain


# --- LIST --------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
def donors_list(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
    q: str = "",
    blood_group: str = "",
    area_id: str = "",
    status: str = "",
    availability: str = "",
    page: int = 1,
) -> HTMLResponse:
    page = max(1, page)
    stmt = select(Donor)
    count_stmt = select(Donor)

    if q:
        like = f"%{q.strip()}%"
        digits = "".join(c for c in q if c.isdigit())
        if digits:
            clause = or_(
                Donor.name.ilike(like),
                Donor.phone_normalized.contains(digits),
            )
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)
        else:
            stmt = stmt.where(Donor.name.ilike(like))
            count_stmt = count_stmt.where(Donor.name.ilike(like))

    if blood_group in BLOOD_GROUPS:
        stmt = stmt.where(Donor.blood_group == blood_group)
        count_stmt = count_stmt.where(Donor.blood_group == blood_group)

    if area_id.isdigit():
        stmt = stmt.where(Donor.area_id == int(area_id))
        count_stmt = count_stmt.where(Donor.area_id == int(area_id))

    if status in {s.value for s in DonorStatus}:
        stmt = stmt.where(Donor.status == status)
        count_stmt = count_stmt.where(Donor.status == status)

    if availability == "available":
        stmt = stmt.where(Donor.is_available == True)  # noqa: E712
        count_stmt = count_stmt.where(Donor.is_available == True)  # noqa: E712
    elif availability == "unavailable":
        stmt = stmt.where(Donor.is_available == False)  # noqa: E712
        count_stmt = count_stmt.where(Donor.is_available == False)  # noqa: E712

    total = len(session.exec(count_stmt).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages

    stmt = stmt.order_by(Donor.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    donors = list(session.exec(stmt).all())

    return templates.TemplateResponse(
        request,
        "coordinator/donors/list.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "donors": donors,
            "areas": _all_areas(session),
            "blood_groups": BLOOD_GROUPS,
            "filters": {
                "q": q,
                "blood_group": blood_group,
                "area_id": area_id,
                "status": status,
                "availability": availability,
            },
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
            "statuses": [s.value for s in DonorStatus],
            "mask_phone": mask_phone,
        },
    )


# --- DETAIL ------------------------------------------------------------------


@router.get("/{donor_id}", response_class=HTMLResponse)
def donor_detail(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
) -> HTMLResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")

    revealed = _is_revealed(request, donor_id)
    contact_attempts = list(
        session.exec(
            select(ContactAttempt)
            .where(ContactAttempt.donor_id == donor_id)
            .order_by(ContactAttempt.created_at.desc())
        ).all()
    )
    new_manage_link = _pop_new_manage_link(request, donor_id)

    return templates.TemplateResponse(
        request,
        "coordinator/donors/detail.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "donor": donor,
            "areas": _all_areas(session),
            "phone_masked": mask_phone(donor.phone_normalized),
            "phone_revealed": donor.phone_normalized if revealed else None,
            "new_manage_link": new_manage_link,
            "contact_attempts": contact_attempts,
            "settings": get_settings(),
            "today": date.today().isoformat(),
            "errors": {},
        },
    )


# --- STATUS CHANGES ----------------------------------------------------------


@router.post("/{donor_id}/verify", dependencies=[CsrfDep])
def donor_verify(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    note: str = Form(default=""),
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    note = (note or "").strip()[:NOTE_MAX_LENGTH]
    donor.status = DonorStatus.VERIFIED.value
    donor.verify_note = note or None
    donor.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.DONOR_VERIFY,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
        detail=("note_set" if note else None),
    )
    session.commit()
    flash(request, "success", "Donor verified.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


@router.post("/{donor_id}/suspend", dependencies=[CsrfDep])
def donor_suspend(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    note: str = Form(default=""),
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    note = (note or "").strip()[:NOTE_MAX_LENGTH]
    donor.status = DonorStatus.SUSPENDED.value
    donor.verify_note = note or donor.verify_note
    donor.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.DONOR_SUSPEND,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
        detail=("note_set" if note else None),
    )
    session.commit()
    flash(request, "success", "Donor suspended.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


@router.post("/{donor_id}/unsuspend", dependencies=[CsrfDep])
def donor_unsuspend(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    donor.status = DonorStatus.VERIFIED.value
    donor.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.DONOR_UNSUSPEND,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
    )
    session.commit()
    flash(request, "success", "Donor reactivated.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


# --- REGENERATE LINK ---------------------------------------------------------


@router.post("/{donor_id}/regenerate-link", dependencies=[CsrfDep])
def donor_regenerate_link(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    plain = new_token(24)
    donor.manage_token_hash = hash_token(plain)
    donor.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.DONOR_REGENERATE_LINK,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
    )
    session.commit()
    new_links = request.session.get("_new_manage_links", {})
    new_links[str(donor.id)] = plain
    request.session["_new_manage_links"] = new_links
    flash(request, "success", "A new manage link has been generated. Save it now — it will not be shown again.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


# --- RECORD DONATION ---------------------------------------------------------


@router.post("/{donor_id}/record-donation", dependencies=[CsrfDep])
def donor_record_donation(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    donation_date: str = Form(...),
    request_token: str = Form(default=""),
    note: str = Form(default=""),
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    # Suspended donors should not be marked as having donated. A donor
    # may have been suspended for a reason (safety flag, age-out, etc.)
    # and recording a donation on their record would mark them eligible
    # again in the next matching pass.
    if donor.status == DonorStatus.SUSPENDED.value:
        flash(
            request,
            "error",
            "Cannot record a donation for a suspended donor. "
            "Unsuspend them first if this is in error.",
        )
        return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)
    try:
        d = date.fromisoformat(donation_date)
    except ValueError:
        flash(request, "error", "Please enter a valid donation date.")
        return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)
    if d > date.today():
        flash(request, "error", "Donation date cannot be in the future.")
        return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)
    # Enforce the 90-day donation gap: a donor who donated recently should
    # not be marked as donating again, or the matching engine's eligibility
    # check (last_donation_date + 90d) becomes a no-op.
    if donor.last_donation_date and d < donor.last_donation_date:
        flash(
            request,
            "error",
            f"Donation date {d} is before the donor's previous donation "
            f"on {donor.last_donation_date}. Refusing to overwrite.",
        )
        return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)
    donor.last_donation_date = d
    donor.updated_at = datetime.now(UTC)

    linked_request: BloodRequest | None = None
    if request_token.strip():
        linked_request = session.exec(
            select(BloodRequest).where(
                BloodRequest.public_token_hash == hash_token(request_token.strip())
            )
        ).first()
        if linked_request is None:
            flash(request, "error", "Request token not found; donation recorded without a link.")
        else:
            session.add(
                ContactAttempt(
                    donor_id=donor.id,
                    request_id=linked_request.id,
                    coordinator_id=current.id,
                    outcome="donated",
                    note=(note or "").strip()[:500] or None,
                )
            )

    detail_bits = [f"date={d.isoformat()}"]
    if linked_request is not None:
        # Don't write the public token to audit detail (F11.1: audit log
        # must not contain PII / secrets; the request_id column above
        # already records which request was linked).
        detail_bits.append("request_linked")
    if note.strip():
        detail_bits.append("note_set")
    write_audit(
        session,
        AuditAction.DONOR_RECORD_DONATION,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
        detail=";".join(detail_bits),
    )
    session.commit()
    flash(request, "success", "Donation recorded.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


# --- REVEAL PHONE ------------------------------------------------------------


@router.post("/{donor_id}/reveal-phone", dependencies=[CsrfDep])
def donor_reveal_phone(
    donor_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
) -> RedirectResponse:
    donor = session.get(Donor, donor_id)
    if not donor:
        raise HTTPException(status_code=404, detail="donor not found")
    write_audit(
        session,
        AuditAction.DONOR_PHONE_REVEAL,
        actor_kind="coordinator",
        coordinator_id=current.id,
        donor_id=donor.id,
    )
    session.commit()
    _mark_revealed(request, donor_id)
    flash(request, "success", "Phone revealed. This action was recorded in the audit log.")
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)


@router.post("/{donor_id}/reveal-phone/clear", dependencies=[CsrfDep])
def donor_clear_revealed_phone(
    donor_id: int,
    request: Request,
    _current: RequireCoordinator,
) -> RedirectResponse:
    _clear_revealed(request, donor_id)
    return RedirectResponse(url=f"/coordinator/donors/{donor_id}", status_code=303)
