"""Telegram Bot API client wrappers (F8.3, F8.4, F8.7, F8.8).

We call only:
  - sendMessage
  - answerCallbackQuery

Network failures (httpx errors) are caught and surfaced as a `(ok, error)`
tuple; the caller decides whether to log, audit, and report to the user.

If TELEGRAM_BOT_TOKEN is not set or DEMO_MODE is on, send_message returns
`(False, "disabled")` without doing any network I/O.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# Reasonable timeout — Telegram is normally fast.
DEFAULT_TIMEOUT = 5.0


class TelegramError(RuntimeError):
    """Raised only by internal test paths. The public send_message API
    never raises; it returns (ok, error)."""


def _is_enabled() -> bool:
    s = get_settings()
    return s.telegram_enabled


def send_message(
    chat_id: str,
    text: str,
    *,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str | None = None,
) -> tuple[bool, str | None]:
    """Send a text message. Returns (ok, error_message). Never raises."""
    if not _is_enabled():
        return False, "disabled"
    token = get_settings().telegram_bot_token
    if not token:
        return False, "missing token"
    url = TELEGRAM_API_BASE.format(token=token, method="sendMessage")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            r = client.post(url, json=payload)
        if r.status_code != 200:
            return False, f"http {r.status_code}"
        data = r.json()
        if not data.get("ok"):
            return False, str(data.get("description") or "telegram error")
        return True, None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("telegram send_message failed: %s", type(exc).__name__)
        return False, type(exc).__name__


def answer_callback_query(
    callback_query_id: str,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> tuple[bool, str | None]:
    """Acknowledge a callback_query. Returns (ok, error_message). Never raises."""
    if not _is_enabled():
        return False, "disabled"
    token = get_settings().telegram_bot_token
    if not token:
        return False, "missing token"
    url = TELEGRAM_API_BASE.format(token=token, method="answerCallbackQuery")
    payload: dict[str, Any] = {
        "callback_query_id": callback_query_id,
        "show_alert": show_alert,
    }
    if text:
        payload["text"] = text[:200]
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            r = client.post(url, json=payload)
        if r.status_code != 200:
            return False, f"http {r.status_code}"
        return True, None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("telegram answer_callback_query failed: %s", type(exc).__name__)
        return False, type(exc).__name__


# --- Notification composition (F8.3) ---------------------------------------


def notify_message_text(
    *,
    blood_group: str,
    hospital_name: str,
    area_name: str,
    needed_by_iso: str,
) -> str:
    """Build the F8.3 notification text. PII is never included."""
    return (
        f"Blood needed: {blood_group}\n"
        f"Hospital: {hospital_name}\n"
        f"Area: {area_name}\n"
        f"Needed by: {needed_by_iso}\n\n"
        "Please respond below. The coordinator will call you to confirm."
    )
