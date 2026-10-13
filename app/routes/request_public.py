"""Public blood request form and requester tracking page (F5, F6).

  GET  /request/new          — public request form
  POST /request/new          — submit a request (honeypot, rate limit, validation)
  GET  /request/{token}      — requester tracking page (status + cancel)
  POST /request/{token}      — cancel an active request

The random public token is shown ONCE on creation (F5.6). It is stored hashed
in DB; the plaintext is the URL path component.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import pop_flashes
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.donor import BLOOD_GROUPS
from app.models.request import BloodRequest, RequestStatus
from app.rate_limit import (
    hash_phone,
    is_ip_rate_limited,
    phone_has_room,
    record_attempt,
)
from app.request_validation import (
    HoneypotTripped,
    RequestValidationError,
    effective_status,
    validate_request_form,
)
from app.templates import make_templates, render_lang_from_request
from app.tokens import hash_token, new_token

router = APIRouter()
templates = make_templates()


def _active_areas(session: Session) -> list[Area]:
    return list(
        session.exec(
            select(Area).where(Area.is_active == True).order_by(Area.name)  # noqa: E712
        ).all()
    )


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


# --- NEW REQUEST --------------------------------------------------------------


@router.get("/request/new", response_class=HTMLResponse)
def request_new_form(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "request/new.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "areas": _active_areas(session),
            "blood_groups": BLOOD_GROUPS,
            "errors": {},
            "values": {},
            "flashes": pop_flashes(request),
        },
    )


@router.post("/request/new", dependencies=[CsrfDep])
def request_new_submit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    blood_group: str = Form(default=""),
    units: str = Form(default=""),
    hospital_name: str = Form(default=""),
    area_id: str = Form(default=""),
    needed_by: str = Form(default=""),
    requester_name: str = Form(default=""),
    requester_phone: str = Form(default=""),
    note: str = Form(default=""),
    consent_contact: str | None = Form(default=None),
    website: str = Form(default=""),  # honeypot (F5.2)
) -> HTMLResponse:
    ip = _client_ip(request)
    now = datetime.now(UTC)

    # F5.2: silent drop. We still log a RequestAttempt row for forensics.
    if website:
        record_attempt(
            session,
            source_ip=ip,
            requester_phone_hash=None,
            accepted=False,
            now=now,
        )
        session.commit()
        # Render the success page so the bot does not know it was caught.
        return templates.TemplateResponse(
            request,
            "request/created.html",
            {
                "lang": render_lang_from_request(request),
                # No token to show; we use a generic placeholder.
                "tracking_link": "/request/honeypot",
                "blood_group": blood_group or "",
                "units": 0,
            },
        )

    # F5.3: per-IP rate limit
    if is_ip_rate_limited(session, ip or "", now):
        record_attempt(
            session,
            source_ip=ip,
            requester_phone_hash=None,
            accepted=False,
            now=now,
        )
        session.commit()
        return templates.TemplateResponse(
            request,
            "request/new.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "areas": _active_areas(session),
                "blood_groups": BLOOD_GROUPS,
                "errors": {"_global": "ip_rate_limited"},
                "values": {
                    "blood_group": blood_group,
                    "units": units,
                    "hospital_name": hospital_name,
                    "area_id": area_id,
                    "needed_by": needed_by,
                    "requester_name": requester_name,
                    "requester_phone": requester_phone,
                    "note": note,
                },
                "flashes": [],
            },
            status_code=429,
        )

    try:
        cleaned = validate_request_form(
            blood_group=blood_group,
            units_raw=units,
            hospital_name=hospital_name,
            area_id_raw=area_id,
            needed_by_raw=needed_by,
            requester_name=requester_name,
            requester_phone=requester_phone,
            note=note,
            honeypot=website,
            consent_contact=consent_contact,
            now=now,
        )
    except RequestValidationError as exc:
        record_attempt(
            session,
            source_ip=ip,
            requester_phone_hash=(
                hash_phone(requester_phone) if requester_phone else None
            ),
            accepted=False,
            now=now,
        )
        session.commit()
        return templates.TemplateResponse(
            request,
            "request/new.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "areas": _active_areas(session),
                "blood_groups": BLOOD_GROUPS,
                "errors": {exc.field: exc.message},
                "values": {
                    "blood_group": blood_group,
                    "units": units,
                    "hospital_name": hospital_name,
                    "area_id": area_id,
                    "needed_by": needed_by,
                    "requester_name": requester_name,
                    "requester_phone": requester_phone,
                    "note": note,
                },
                "flashes": [],
            },
            status_code=400,
        )
    except HoneypotTripped:
        # Same as inline honeypot path; the inline check above is the
        # primary guard, so this branch is defensive.
        record_attempt(
            session, source_ip=ip, requester_phone_hash=None, accepted=False, now=now
        )
        session.commit()
        return templates.TemplateResponse(
            request,
            "request/created.html",
            {
                "lang": render_lang_from_request(request),
                "tracking_link": "/request/honeypot",
                "blood_group": blood_group or "",
                "units": 0,
            },
        )

    # F5.4: per-phone active-request cap
    if not phone_has_room(session, cleaned["requester_phone"]):
        record_attempt(
            session,
            source_ip=ip,
            requester_phone_hash=hash_phone(cleaned["requester_phone"]),
            accepted=False,
            now=now,
        )
        session.commit()
        return templates.TemplateResponse(
            request,
            "request/new.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "areas": _active_areas(session),
                "blood_groups": BLOOD_GROUPS,
                "errors": {"requester_phone": "phone_too_many"},
                "values": {
                    "blood_group": blood_group,
                    "units": units,
                    "hospital_name": hospital_name,
                    "area_id": area_id,
                    "needed_by": needed_by,
                    "requester_name": requester_name,
                    "requester_phone": requester_phone,
                    "note": note,
                },
                "flashes": [],
            },
            status_code=400,
        )

    # Area must exist + be active
    area = session.get(Area, cleaned["area_id"])
    if not area or not area.is_active:
        return templates.TemplateResponse(
            request,
            "request/new.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "areas": _active_areas(session),
                "blood_groups": BLOOD_GROUPS,
                "errors": {"area_id": "Please choose a valid area."},
                "values": {
                    "blood_group": blood_group,
                    "units": units,
                    "hospital_name": hospital_name,
                    "area_id": area_id,
                    "needed_by": needed_by,
                    "requester_name": requester_name,
                    "requester_phone": requester_phone,
                    "note": note,
                },
                "flashes": [],
            },
            status_code=400,
        )

    # Generate the tracking token (F5.5, F5.6). Only the hash is persisted
    # (F11.1: secrets must be hashed at rest); the plaintext is shown to
    # the requester ONCE in the response so they can save the URL.
    plain = new_token(24)
    req = BloodRequest(
        public_token_hash=hash_token(plain),
        blood_group=cleaned["blood_group"],
        units=cleaned["units"],
        hospital_name=cleaned["hospital_name"],
        area_id=area.id,
        needed_by=cleaned["needed_by"],
        requester_name=cleaned["requester_name"],
        requester_phone_normalized=cleaned["requester_phone"],
        note=cleaned["note"],
        consent_contact=cleaned["consent_contact"],
        status=RequestStatus.PENDING.value,
        source_ip=ip,
    )
    session.add(req)
    session.flush()
    record_attempt(
        session,
        source_ip=ip,
        requester_phone_hash=hash_phone(cleaned["requester_phone"]),
        accepted=True,
        request_id=req.id,
        now=now,
    )
    write_audit(
        session,
        AuditAction.REQUEST_CREATE,
        actor_kind="anonymous",
        request_id=req.id,
    )
    session.commit()

    return templates.TemplateResponse(
        request,
        "request/created.html",
        {
            "lang": render_lang_from_request(request),
            "tracking_link": f"/request/{plain}",
            "blood_group": cleaned["blood_group"],
            "units": cleaned["units"],
        },
    )


# --- TRACKING -----------------------------------------------------------------


@router.get("/request/{token}", response_class=HTMLResponse)
def request_track(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    req = session.exec(
        select(BloodRequest).where(
            BloodRequest.public_token_hash == hash_token(token)
        )
    ).first()
    if not req:
        # F6.4: no info leak. Same page, generic message.
        return templates.TemplateResponse(
            request,
            "request/tracking.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": "",
                "not_found": True,
                "req": None,
                "effective": None,
                "flashes": [],
            },
        )
    return templates.TemplateResponse(
        request,
        "request/tracking.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "not_found": False,
            "req": req,
            # The plaintext token is only available in the URL the requester
            # is currently holding. We pass it through so the cancel form
            # can POST to /request/{token} again, but it is never persisted
            # in the DB (only the SHA-256 hash is).
            "public_token": token,
            "effective": effective_status(req.status, req.needed_by),
            "flashes": pop_flashes(request),
        },
    )


@router.post("/request/{token}", dependencies=[CsrfDep])
def request_cancel(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> RedirectResponse:
    req = session.exec(
        select(BloodRequest).where(
            BloodRequest.public_token_hash == hash_token(token)
        )
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="not found")
    # Cancellation is only allowed while still active.
    eff = effective_status(req.status, req.needed_by)
    if eff in {
        RequestStatus.FULFILLED.value,
        RequestStatus.CANCELLED.value,
        RequestStatus.REJECTED.value,
        RequestStatus.EXPIRED.value,
    }:
        # No-op but redirect to the tracking page so the user sees the
        # current status.
        return RedirectResponse(url=f"/request/{token}", status_code=303)
    req.status = RequestStatus.CANCELLED.value
    req.closed_at = datetime.now(UTC)
    req.updated_at = datetime.now(UTC)
    write_audit(
        session,
        AuditAction.REQUEST_CANCEL,
        actor_kind="requester",
        request_id=req.id,
    )
    session.commit()
    return RedirectResponse(url=f"/request/{token}", status_code=303)
