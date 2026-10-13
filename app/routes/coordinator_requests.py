"""Coordinator blood request management (F6).

  GET  /coordinator/requests                 — list, filter, paginate
  GET  /coordinator/requests/{rid}           — detail
  POST /coordinator/requests/{rid}/verify    — mark verified
  POST /coordinator/requests/{rid}/reject    — mark rejected (with reason)
  POST /coordinator/requests/{rid}/fulfill   — mark fulfilled

Only verified requests can be matched (F6.2, F6.3) — that is enforced in
the matching engine (M6) and we do not provide a direct "match" endpoint
yet (the candidate list lives in /coordinator/matching).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, or_, select

from app.audit import write_audit
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import RequireCoordinator, flash, pop_flashes
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.donor import BLOOD_GROUPS
from app.models.request import BloodRequest, RequestStatus
from app.request_validation import effective_status
from app.templates import make_templates, render_lang_from_request
from app.tokens import hash_token

router = APIRouter(prefix="/coordinator/requests")
templates = make_templates()

PAGE_SIZE = 25


def _all_areas(session: Session) -> list[Area]:
    return list(session.exec(select(Area).order_by(Area.name)).all())


@router.get("", response_class=HTMLResponse)
def requests_list(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
    q: str = "",
    blood_group: str = "",
    area_id: str = "",
    status: str = "",
    page: int = 1,
) -> HTMLResponse:
    page = max(1, page)
    stmt = select(BloodRequest)
    count_stmt = select(BloodRequest)

    if q:
        like = f"%{q.strip()}%"
        digits = "".join(c for c in q if c.isdigit())
        # The public token is stored as a SHA-256 hash, so we cannot
        # substring-match it. If the user pastes what looks like a token,
        # we hash it and look for an exact match. Otherwise we fall back to
        # the other searchable fields.
        clauses: list = [
            BloodRequest.hospital_name.ilike(like),
            BloodRequest.requester_name.ilike(like),
        ]
        token_guess = q.strip()
        if token_guess and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-." for c in token_guess):
            # best-effort: if the search string is a possible token, also
            # try hashing it. Use OR so unrelated searches still work.
            clauses.append(
                BloodRequest.public_token_hash == hash_token(token_guess)
            )
        if digits:
            clauses.append(BloodRequest.requester_phone_normalized.contains(digits))
        clause = or_(*clauses)
        stmt = stmt.where(clause)
        count_stmt = count_stmt.where(clause)

    if blood_group in BLOOD_GROUPS:
        stmt = stmt.where(BloodRequest.blood_group == blood_group)
        count_stmt = count_stmt.where(BloodRequest.blood_group == blood_group)

    if area_id.isdigit():
        stmt = stmt.where(BloodRequest.area_id == int(area_id))
        count_stmt = count_stmt.where(BloodRequest.area_id == int(area_id))

    if status in {s.value for s in RequestStatus}:
        stmt = stmt.where(BloodRequest.status == status)
        count_stmt = count_stmt.where(BloodRequest.status == status)

    total = len(session.exec(count_stmt).all())
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > total_pages:
        page = total_pages

    stmt = (
        stmt.order_by(BloodRequest.needed_by.asc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )
    requests = list(session.exec(stmt).all())

    return templates.TemplateResponse(
        request,
        "coordinator/requests/list.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            "requests": requests,
            "areas": _all_areas(session),
            "blood_groups": BLOOD_GROUPS,
            "statuses": [s.value for s in RequestStatus],
            "filters": {
                "q": q,
                "blood_group": blood_group,
                "area_id": area_id,
                "status": status,
            },
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "total_pages": total_pages,
            "effective_status": effective_status,
        },
    )


@router.get("/{rid}", response_class=HTMLResponse)
def request_detail(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    _current: RequireCoordinator,
) -> HTMLResponse:
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    area = session.get(Area, req.area_id) if req.area_id else None
    return templates.TemplateResponse(
        request,
        "coordinator/requests/detail.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "flashes": pop_flashes(request),
            # Use `request_obj` not `request` — Starlette internally
            # calls request.get(...) on the first arg, and a context key
            # named `request` shadows it. This was previously dormant
            # because no test loaded the detail page directly.
            "request_obj": req,
            "area": area,
            "effective": effective_status(req.status, req.needed_by),
        },
    )


@router.post("/{rid}/verify", dependencies=[CsrfDep])
def request_verify(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
) -> RedirectResponse:
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status not in {RequestStatus.PENDING.value, RequestStatus.VERIFIED.value}:
        flash(request, "error", "Only pending or verified requests can be verified.")
        return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
    req.status = RequestStatus.VERIFIED.value
    req.verified_by_id = current.id
    req.verified_at = datetime.now(UTC)
    req.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.REQUEST_VERIFY,
        actor_kind="coordinator",
        coordinator_id=current.id,
        request_id=req.id,
    )
    session.commit()
    flash(request, "success", "Request verified.")
    return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)


@router.post("/{rid}/reject", dependencies=[CsrfDep])
def request_reject(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    reason: str = Form(...),
) -> RedirectResponse:
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status in {
        RequestStatus.FULFILLED.value,
        RequestStatus.CANCELLED.value,
        RequestStatus.REJECTED.value,
    }:
        flash(request, "error", "This request can no longer be rejected.")
        return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
    reason = (reason or "").strip()[:500]
    if not reason:
        flash(request, "error", "Please provide a reason for rejection.")
        return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
    req.status = RequestStatus.REJECTED.value
    req.reject_reason = reason
    req.verified_by_id = current.id
    req.verified_at = datetime.now(UTC)
    req.closed_at = datetime.now(UTC)
    req.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.REQUEST_REJECT,
        actor_kind="coordinator",
        coordinator_id=current.id,
        request_id=req.id,
        detail=reason,
    )
    session.commit()
    flash(request, "success", "Request rejected.")
    return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)


@router.post("/{rid}/fulfill", dependencies=[CsrfDep])
def request_fulfill(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
) -> RedirectResponse:
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status not in {
        RequestStatus.VERIFIED.value,
        RequestStatus.PENDING.value,
    }:
        flash(request, "error", "Only pending or verified requests can be fulfilled.")
        return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
    req.status = RequestStatus.FULFILLED.value
    req.closed_at = datetime.now(UTC)
    req.updated_at = datetime.now(UTC)
    # If the request was PENDING (skipped the explicit verify step),
    # we still need to record who closed it as the verifier. Otherwise
    # downstream reports that filter "verified by" would silently miss
    # these requests.
    if req.verified_by_id is None:
        req.verified_by_id = current.id
        req.verified_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.REQUEST_FULFILL,
        actor_kind="coordinator",
        coordinator_id=current.id,
        request_id=req.id,
    )
    session.commit()
    flash(request, "success", "Request marked fulfilled.")
    return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
