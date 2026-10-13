"""Coordinator-side Telegram notification trigger (F8.3, F8.7, F8.8).

The coordinator selects one or more candidates on the matching page and
clicks "Notify via Telegram". For each candidate, we look up the linked
chat_id, build the F8.3 message, and call the Telegram API. Failures are
recorded on the contact attempt and surfaced to the coordinator.

If Telegram is not enabled, the route returns 200 with a flash saying
"notifications are disabled" and does no network I/O.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.config import get_settings
from app.csrf import CsrfDep
from app.db import get_session
from app.deps import RequireCoordinator, flash
from app.models.area import Area
from app.models.audit_log import AuditAction
from app.models.contact_attempt import ContactAttempt
from app.models.donor import Donor
from app.models.request import BloodRequest
from app.models.telegram_link import TelegramLink
from app.telegram import notify_message_text, send_message
from app.telegram_signing import make_accept_token, make_decline_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coordinator/requests")


def _bot_username_or_none() -> str | None:
    """Read the configured bot username (TELEGRAM_PUBLIC_BASE_URL) if set.

    Used to build a deep link like https://t.me/<bot>?start=<code>.
    """
    base = get_settings().telegram_public_base_url
    if not base:
        return None
    base = base.strip().rstrip("/")
    if base.startswith("https://t.me/"):
        return base.removeprefix("https://t.me/")
    if base.startswith("http://t.me/"):
        return base.removeprefix("http://t.me/")
    return None


def _build_bot_start_url(code: str) -> str | None:
    bot = _bot_username_or_none()
    if not bot:
        return None
    return f"https://t.me/{bot}?start={code}"


@router.post("/{rid}/notify", dependencies=[CsrfDep])
def notify_candidates(
    rid: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    current: RequireCoordinator,
    donor_ids: str = Form(...),  # comma-separated donor ids
) -> RedirectResponse:
    settings = get_settings()
    req = session.get(BloodRequest, rid)
    if not req:
        raise HTTPException(status_code=404, detail="request not found")
    if req.status != "verified":
        flash(request, "error", "Only verified requests can be notified.")
        return RedirectResponse(url=f"/coordinator/requests/{rid}", status_code=303)
    if not settings.telegram_enabled:
        flash(
            request,
            "error",
            "Telegram notifications are disabled. Set TELEGRAM_BOT_TOKEN to enable.",
        )
        return RedirectResponse(
            url=f"/coordinator/matching/{rid}", status_code=303
        )
    area = session.get(Area, req.area_id) if req.area_id else None
    area_name = area.name if area else str(req.area_id or "")
    try:
        ids = [int(x) for x in donor_ids.split(",") if x.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad donor_ids") from exc
    if not ids:
        raise HTTPException(status_code=400, detail="no donors selected")

    success = 0
    failures: list[tuple[int, str]] = []  # (donor_id, reason)
    for donor_id in ids:
        donor = session.get(Donor, donor_id)
        if not donor or donor.id is None:
            continue
        link = session.exec(
            select(TelegramLink).where(TelegramLink.donor_id == donor.id)
        ).first()
        if not link or not link.chat_id:
            failures.append((donor.id, "no chat link"))
            continue
        # Create the contact attempt first so the inline buttons have an id
        attempt = ContactAttempt(
            donor_id=donor.id,
            request_id=req.id,
            coordinator_id=current.id,
            outcome="contacted",
        )
        session.add(attempt)
        session.flush()
        text = notify_message_text(
            blood_group=req.blood_group,
            hospital_name=req.hospital_name,
            area_name=area_name,
            needed_by_iso=req.needed_by.isoformat(),
        )
        markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "Accept",
                        "callback_data": make_accept_token(req.id, donor.id, attempt.id),
                    },
                    {
                        "text": "Decline",
                        "callback_data": make_decline_token(req.id, donor.id, attempt.id),
                    },
                ]
            ]
        }
        ok, err = send_message(link.chat_id, text, reply_markup=markup)
        if ok:
            write_audit(
                session,
                AuditAction.TELEGRAM_NOTIFY_SENT,
                actor_kind="coordinator",
                coordinator_id=current.id,
                donor_id=donor.id,
                request_id=req.id,
                contact_attempt_id=attempt.id,
            )
            success += 1
        else:
            attempt.outcome = "no_answer"  # mark as not contacted
            write_audit(
                session,
                AuditAction.TELEGRAM_NOTIFY_FAILED,
                actor_kind="coordinator",
                coordinator_id=current.id,
                donor_id=donor.id,
                request_id=req.id,
                contact_attempt_id=attempt.id,
                detail=err or "unknown",
            )
            failures.append((donor.id, err or "unknown"))
    session.commit()
    if success:
        flash(request, "success", f"Notified {success} donor(s) via Telegram.")
    if failures:
        flash(
            request,
            "error",
            f"Could not notify {len(failures)} donor(s): " + "; ".join(
                f"#{d} ({r})" for d, r in failures
            ),
        )
    return RedirectResponse(url=f"/coordinator/matching/{rid}", status_code=303)
