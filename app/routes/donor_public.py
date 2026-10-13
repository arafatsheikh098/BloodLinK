"""Public donor registration form + donor self-service via manage link (F2, F3)."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.config import get_settings
from app.csrf import CsrfDep, get_or_create_csrf
from app.db import get_session
from app.deps import pop_flashes
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.donor import BLOOD_GROUPS, Donor, DonorStatus
from app.models.telegram_link import TelegramLink
from app.phone import (
    PhoneNormalizationError,
    mask_phone,
    normalize_bd_mobile,
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


@router.get("/donor/register", response_class=HTMLResponse)
def register_form(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    areas = _active_areas(session)
    return templates.TemplateResponse(
        request,
        "donor/register.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "areas": areas,
            "errors": {},
            "values": {},
            "blood_groups": BLOOD_GROUPS,
            "flashes": pop_flashes(request),
        },
    )


@router.post("/donor/register", dependencies=[CsrfDep])
def register_submit(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    name: str = Form(...),
    blood_group: str = Form(...),
    phone: str = Form(...),
    area_id: int = Form(...),
    last_donation_date: str = Form(default=""),
    is_over_18: str | None = Form(default=None),
    consent_contact: str | None = Form(default=None),
    consent_verify: str | None = Form(default=None),
) -> HTMLResponse:
    errors: dict[str, str] = {}

    # Validate name (no XSS in render — Jinja autoescape handles it anyway)
    name = (name or "").strip()
    if not (1 <= len(name) <= 120):
        errors["name"] = "Please enter your name."

    if blood_group not in BLOOD_GROUPS:
        errors["blood_group"] = "Please choose a valid blood group."

    # Phone normalization
    try:
        normalized_phone = normalize_bd_mobile(phone)
    except PhoneNormalizationError as exc:
        errors["phone"] = str(exc)

    # Area must exist and be active
    area = session.get(Area, area_id)
    if not area or not area.is_active:
        errors["area_id"] = "Please choose a valid area."

    # Last donation date (optional, not in the future)
    ldd: date | None = None
    if last_donation_date:
        try:
            ldd = date.fromisoformat(last_donation_date)
        except ValueError:
            errors["last_donation_date"] = "Please enter a valid date."
        else:
            if ldd > date.today():
                errors["last_donation_date"] = (
                    "Last donation date cannot be in the future."
                )

    # Checkboxes
    if not is_over_18:
        errors["is_over_18"] = "You must confirm you are 18 or older."
    if not consent_contact:
        errors["consent_contact"] = "Please confirm consent to be contacted."
    if not consent_verify:
        errors["consent_verify"] = "Please confirm you understand verification."

    if "phone" not in errors:
        # Duplicate phone rejection (G6)
        existing = session.exec(
            select(Donor).where(Donor.phone_normalized == normalized_phone)
        ).first()
        if existing:
            # We must NOT reveal that the phone is already registered. Show a generic
            # error that does not confirm whether the number exists.
            errors["phone"] = (
                "We could not register this number. If you already registered, "
                "use the manage link we showed you earlier."
            )

    if errors:
        return templates.TemplateResponse(
            request,
            "donor/register.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "areas": _active_areas(session),
                "errors": errors,
                "values": {
                    "name": name,
                    "blood_group": blood_group,
                    "phone": phone,
                    "area_id": area_id,
                    "last_donation_date": last_donation_date,
                },
                "blood_groups": BLOOD_GROUPS,
                "flashes": [],
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Generate the one-time manage link token (192 bits).
    plain_token = new_token(24)
    donor = Donor(
        manage_token_hash=hash_token(plain_token),
        name=name,
        blood_group=blood_group,
        phone_normalized=normalized_phone,
        area_id=area.id,
        last_donation_date=ldd,
        is_available=True,
        status=DonorStatus.UNVERIFIED.value,
        is_over_18=bool(is_over_18),
        consent_contact=bool(consent_contact),
        consent_verify=bool(consent_verify),
    )
    session.add(donor)
    session.flush()
    write_audit(
        session,
        "donor_register",
        actor_kind="anonymous",
        donor_id=donor.id,
    )
    session.commit()

    # Render the success page once. We never re-show this token.
    return templates.TemplateResponse(
        request,
        "donor/registered.html",
        {
            "lang": render_lang_from_request(request),
            "manage_link": f"/donor/manage/{plain_token}",
            "phone_masked": mask_phone(normalized_phone),
        },
    )


@router.get("/donor/manage/{token}", response_class=HTMLResponse)
def manage_form(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> HTMLResponse:
    donor = session.exec(
        select(Donor).where(Donor.manage_token_hash == hash_token(token))
    ).first()
    if not donor:
        # No info leak: 404 with no detail.
        raise HTTPException(status_code=404, detail="not found")
    areas = _active_areas(session)
    telegram_link = session.exec(
        select(TelegramLink).where(TelegramLink.donor_id == donor.id)
    ).first()
    bot_username = None
    pending_code = None
    bot_start_url = None
    if get_settings().telegram_enabled:
        from app.routes.telegram import _new_link_code

        bot_username = _bot_username()
        if telegram_link and telegram_link.chat_id:
            # Already linked
            pending_code = None
        else:
            # Issue a fresh pending code (or reuse the live one)
            if (
                telegram_link
                and telegram_link.pending_code_hash
                and telegram_link.pending_code_expires_at
                and telegram_link.pending_code_expires_at.replace(tzinfo=None)
                > datetime.now(UTC).replace(tzinfo=None)
            ):
                # We cannot show the plaintext old code (we only have its hash)
                # so generate a fresh one.
                pass
            if telegram_link is None:
                telegram_link = TelegramLink(donor_id=donor.id)
                session.add(telegram_link)
            plain_code = _new_link_code()
            telegram_link.pending_code_hash = hash_token(plain_code)
            telegram_link.pending_code_expires_at = (
                datetime.now(UTC) + timedelta(minutes=15)
            )
            telegram_link.updated_at = datetime.now(UTC)
            session.commit()
            pending_code = plain_code
            if bot_username:
                bot_start_url = f"https://t.me/{bot_username}?start={plain_code}"
    return templates.TemplateResponse(
        request,
        "donor/manage.html",
        {
            "lang": render_lang_from_request(request),
            "csrf_token": get_or_create_csrf(request),
            "donor": donor,
            "phone_masked": mask_phone(donor.phone_normalized),
            "areas": areas,
            "token": token,
            "flashes": pop_flashes(request),
            "errors": {},
            "blood_groups": BLOOD_GROUPS,
            "telegram_enabled": get_settings().telegram_enabled,
            "telegram_linked": bool(telegram_link and telegram_link.chat_id),
            "telegram_pending_code": pending_code,
            "telegram_bot_username": bot_username,
            "telegram_bot_start_url": bot_start_url,
        },
    )


def _bot_username() -> str | None:
    from app.config import get_settings

    base = get_settings().telegram_public_base_url
    if not base:
        return None
    base = base.strip().rstrip("/")
    if base.startswith("https://t.me/"):
        return base.removeprefix("https://t.me/")
    if base.startswith("http://t.me/"):
        return base.removeprefix("http://t.me/")
    return None


@router.post("/donor/manage/{token}", dependencies=[CsrfDep])
def manage_submit(
    token: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    is_available: str | None = Form(default=None),
    area_id: int | None = Form(default=None),
    last_donation_date: str = Form(default=""),
    phone: str = Form(default=""),
    action: str = Form(default="update"),
) -> RedirectResponse:
    donor = session.exec(
        select(Donor).where(Donor.manage_token_hash == hash_token(token))
    ).first()
    if not donor:
        raise HTTPException(status_code=404, detail="not found")

    if action == "delete":
        # F3.5: hard-delete the donor row + PII. Anonymous audit entry remains.
        donor_id = donor.id
        # Delete contact attempts that reference this donor (CASCADE in DB would also work).
        from app.models.contact_attempt import ContactAttempt

        attempts = list(
            session.exec(
                select(ContactAttempt).where(ContactAttempt.donor_id == donor_id)
            ).all()
        )
        for a in attempts:
            session.delete(a)
        # Null out audit references; we keep anonymous entries.
        from app.models.audit_log import AuditLog

        audit_rows = list(
            session.exec(select(AuditLog).where(AuditLog.donor_id == donor_id)).all()
        )
        for row in audit_rows:
            row.donor_id = None
            row.detail = None
        # Insert an anonymous audit row
        write_audit(
            session,
            AuditAction.DONOR_SELF_DELETE,
            actor_kind="donor",
            detail="anonymous",
        )
        session.delete(donor)
        session.commit()
        raise HTTPException(status_code=404, detail="not found")

    # Update path
    errors: dict[str, str] = {}

    # Availability
    donor.is_available = bool(is_available)

    # Area
    if area_id is None:
        errors["area_id"] = "Please choose a valid area."
    else:
        area = session.get(Area, area_id)
        if not area or not area.is_active:
            errors["area_id"] = "Please choose a valid area."
        else:
            donor.area_id = area_id

    # Last donation date (optional)
    if last_donation_date:
        try:
            ldd = date.fromisoformat(last_donation_date)
            if ldd > date.today():
                errors["last_donation_date"] = (
                    "Last donation date cannot be in the future."
                )
            else:
                donor.last_donation_date = ldd
        except ValueError:
            errors["last_donation_date"] = "Please enter a valid date."
    else:
        donor.last_donation_date = None

    # Phone update (resets to unverified if changed)
    phone_changed = False
    if phone:
        try:
            new_norm = normalize_bd_mobile(phone)
            if new_norm != donor.phone_normalized:
                # Verify uniqueness (excluding self)
                clash = session.exec(
                    select(Donor).where(
                        Donor.phone_normalized == new_norm, Donor.id != donor.id
                    )
                ).first()
                if clash:
                    errors["phone"] = (
                        "This number is already registered to another donor."
                    )
                else:
                    donor.phone_normalized = new_norm
                    donor.status = DonorStatus.UNVERIFIED.value
                    phone_changed = True
        except PhoneNormalizationError as exc:
            errors["phone"] = str(exc)

    donor.updated_at = datetime.now(UTC)

    if errors:
        return templates.TemplateResponse(
            request,
            "donor/manage.html",
            {
                "lang": render_lang_from_request(request),
                "csrf_token": get_or_create_csrf(request),
                "donor": donor,
                "phone_masked": mask_phone(donor.phone_normalized),
                "areas": _active_areas(session),
                "token": token,
                "flashes": [],
                "errors": errors,
                "blood_groups": BLOOD_GROUPS,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    session.commit()
    request.session["_flashes"] = request.session.get("_flashes", []) + [
        {"level": "success", "message": "Saved." if not phone_changed else "Phone updated; a coordinator will verify you again."}
    ]
    return RedirectResponse(url=f"/donor/manage/{token}", status_code=303)