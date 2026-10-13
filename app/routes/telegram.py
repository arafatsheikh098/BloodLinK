"""Telegram routes (F8.1, F8.2, F8.4).

  POST /telegram/webhook         — receive updates (header-secret check)
  GET  /telegram/connect/{code}  — donor manage-page entrypoint (no-op)

The webhook URL must be set via the BotFather API after deploy. Telegram
sends an X-Telegram-Bot-Api-Secret-Token header that we compare in constant
time to TELEGRAM_WEBHOOK_SECRET. The /start command from a donor is
received via the webhook and processed by _link_chat_to_donor below.
"""
from __future__ import annotations

import hmac
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from app.audit import write_audit
from app.config import get_settings
from app.db import get_session
from app.models.audit_log import AuditAction
from app.models.contact_attempt import ContactAttempt
from app.models.telegram_link import TelegramLink
from app.telegram_signing import verify_callback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram")

LINK_CODE_TTL = timedelta(minutes=15)
LINK_CODE_BYTES = 9  # ~72 bits — fine for a single-use short code


def _new_link_code() -> str:
    """Return a short, human-friendly one-time code.

    Six base32-like chars (no 0/1 to avoid confusion). Used for the
    donor → bot link step.
    """
    import secrets

    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # omit 0/1/I/O
    return "".join(secrets.choice(alphabet) for _ in range(8))


# --- Webhook ----------------------------------------------------------------


@router.post("/webhook", response_class=PlainTextResponse)
async def webhook(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> PlainTextResponse:
    """Receive Telegram updates. F8.4 — secret header check.

    We accept only the very small set of updates we care about:
      - /start <code>     — link the chat_id to a donor
      - callback_query    — accept / decline from a notification button
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=404, detail="telegram not configured")
    if not settings.telegram_webhook_secret:
        # We refuse to operate without a secret (F8.4).
        raise HTTPException(status_code=403, detail="webhook not configured")
    header = request.headers.get("x-telegram-bot-api-secret-token", "")
    if not hmac.compare_digest(header, settings.telegram_webhook_secret):
        raise HTTPException(status_code=403, detail="bad secret")

    payload = await request.json()
    if not isinstance(payload, dict):
        # Malformed update; ack so Telegram doesn't retry forever.
        return PlainTextResponse("ok")
    await _handle_update(payload, session)
    return PlainTextResponse("ok")


# --- /start link handling ---------------------------------------------------


async def _handle_update(update: dict, session: Session) -> None:
    """Process a single Telegram update."""
    if not isinstance(update, dict):
        return
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        _handle_callback(callback_query, session)
        return
    message = update.get("message") or update.get("edited_message")
    if not isinstance(message, dict):
        return
    text = (message.get("text") or "").strip()
    if not text.startswith("/start"):
        return
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) == 2 else ""
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    from_user = message.get("from") or {}
    user_id = str(from_user.get("id") or chat_id)
    if not code or not chat_id:
        return
    _link_chat_to_donor(code=code, chat_id=chat_id, user_id=user_id, session=session)


def _link_chat_to_donor(
    *, code: str, chat_id: str, user_id: str, session: Session
) -> None:
    from app.tokens import hash_token

    code_hash = hash_token(code)
    now = datetime.now(UTC)
    link = session.exec(
        select(TelegramLink).where(TelegramLink.pending_code_hash == code_hash)
    ).first()
    if not link or not link.pending_code_expires_at:
        write_audit(
            session,
            AuditAction.TELEGRAM_CALLBACK_REJECTED,
            actor_kind="anonymous",
            detail="link_code_not_found",
        )
        session.commit()
        return
    expires_at = link.pending_code_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        write_audit(
            session,
            AuditAction.TELEGRAM_CALLBACK_REJECTED,
            actor_kind="anonymous",
            donor_id=link.donor_id,
            detail="link_code_expired",
        )
        session.commit()
        return
    if link.chat_id is not None and link.chat_id != chat_id:
        # Already linked to a different chat — refuse.
        write_audit(
            session,
            AuditAction.TELEGRAM_CALLBACK_REJECTED,
            actor_kind="anonymous",
            donor_id=link.donor_id,
            detail="link_chat_mismatch",
        )
        session.commit()
        return
    link.chat_id = chat_id
    link.pending_code_hash = None
    link.pending_code_expires_at = None
    link.updated_at = now
    write_audit(
        session,
        AuditAction.TELEGRAM_LINK_COMPLETE,
        actor_kind="donor",
        donor_id=link.donor_id,
        # No chat_id in detail — F11.1: the audit log must not contain
        # identifiers that could pin a person.
    )
    session.commit()


# --- Accept/Decline callback handling --------------------------------------


def _handle_callback(callback_query: dict, session: Session) -> None:
    """F8.5 / F8.6 — idempotent accept or decline."""
    from app.telegram import answer_callback_query

    data = callback_query.get("data") or ""
    cq_id = callback_query.get("id") or ""
    payload = verify_callback(data)
    if not payload:
        answer_callback_query(cq_id, text="Link expired or invalid.")
        write_audit(
            session,
            AuditAction.TELEGRAM_CALLBACK_REJECTED,
            actor_kind="donor",
            detail="bad_signature",
        )
        session.commit()
        return
    variant = payload.get("v")
    request_id = int(payload.get("r") or 0)
    donor_id = int(payload.get("d") or 0)
    attempt_id = int(payload.get("a") or 0)
    if variant not in {"accept", "decline"} or not (request_id and donor_id and attempt_id):
        answer_callback_query(cq_id, text="Link invalid.")
        return
    # Look up the attempt; if it already has an outcome, this is a duplicate.
    attempt = session.get(ContactAttempt, attempt_id)
    if not attempt or attempt.request_id != request_id or attempt.donor_id != donor_id:
        answer_callback_query(cq_id, text="This request is no longer active.")
        return
    if attempt.outcome in {"accepted", "declined", "donated"}:
        # F8.6: idempotent — don't change state; just acknowledge.
        answer_callback_query(
            cq_id, text=f"Already recorded as {attempt.outcome}."
        )
        return
    # Verify that this chat_id matches the linked donor's chat (defense in depth)
    link = session.exec(
        select(TelegramLink).where(TelegramLink.donor_id == donor_id)
    ).first()
    if not link or link.chat_id != str(callback_query.get("from", {}).get("id", "")):
        answer_callback_query(cq_id, text="This button is not for your account.")
        return
    if variant == "accept":
        attempt.outcome = "accepted"
        action = AuditAction.TELEGRAM_CALLBACK_ACCEPT
        text = "Thanks! The coordinator will call you."
    else:
        attempt.outcome = "declined"
        action = AuditAction.TELEGRAM_CALLBACK_DECLINE
        text = "Got it, thanks for letting us know."
    session.add(attempt)
    write_audit(
        session,
        action,
        actor_kind="donor",
        donor_id=donor_id,
        request_id=request_id,
        contact_attempt_id=attempt_id,
        # No chat_id in detail — F11.1.
    )
    session.commit()
    answer_callback_query(cq_id, text=text)


# --- Donor manage-page entrypoint ------------------------------------------


@router.get("/connect/{code}")
def connect_get(code: str) -> PlainTextResponse:
    """GET is documented as a no-op — donors must open the link in Telegram."""
    return PlainTextResponse(
        "Please open this link inside the Telegram app to link your account.",
        status_code=200,
    )
