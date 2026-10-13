"""Bangladesh mobile number normalization.

Accepts:
  - 01712345678
  - +8801712345678
  - 8801712345678
  - 017-1234-5678

Rejects:
  - invalid operator digit (0, 1, 2 at position 3 after country code)
  - landline-style numbers
  - too short / too long inputs
  - anything with non-digit characters after stripping common separators

Normalized form: +8801XXXXXXXXX (operator digit 3-9, 8 remaining digits).
"""
from __future__ import annotations

import re
from typing import Final

# 8 digits follow the operator digit in the canonical form.
LOCAL_TAIL_LENGTH: Final = 8
NORMALIZED_REGEX: Final[re.Pattern[str]] = re.compile(r"^\+8801[3-9]\d{8}$")

# Separators we strip before validation.
_SEPARATORS: Final[re.Pattern[str]] = re.compile(r"[\s\-()]+")


class PhoneNormalizationError(ValueError):
    """Raised when a phone number is invalid."""


def _strip_to_digits(raw: str) -> str:
    return _SEPARATORS.sub("", raw or "")


def normalize_bd_mobile(raw: str) -> str:
    """Return the canonical +8801XXXXXXXXX form, or raise PhoneNormalizationError."""
    if raw is None:
        raise PhoneNormalizationError("phone is required")
    digits = _strip_to_digits(str(raw))
    if not digits:
        raise PhoneNormalizationError("phone is required")

    # Local body always starts with "1" followed by 9 digits (1 + operator + 8).
    if digits.startswith("+880"):
        body = digits[4:]
    elif digits.startswith("880"):
        body = digits[3:]
    elif digits.startswith("0"):
        body = digits[1:]
    else:
        # Already bare: 1XXXXXXXXX
        body = digits

    if not body.startswith("1"):
        raise PhoneNormalizationError("phone must start with 1 after country code")

    # body is 1XXXXXXXXX (10 digits). body[1] is the operator digit.
    if len(body) != 1 + 1 + LOCAL_TAIL_LENGTH:
        raise PhoneNormalizationError("phone length is invalid")

    if not body.isdigit():
        raise PhoneNormalizationError("phone contains non-digit characters")

    if body[1] not in "3456789":
        raise PhoneNormalizationError("operator digit is invalid")

    normalized = f"+880{body}"
    if not NORMALIZED_REGEX.match(normalized):
        raise PhoneNormalizationError("phone failed final validation")
    return normalized


def is_valid_bd_mobile(raw: str) -> bool:
    try:
        normalize_bd_mobile(raw)
        return True
    except PhoneNormalizationError:
        return False


def mask_phone(normalized: str) -> str:
    """Return a masked display form, e.g. +88017••••••678 (6 bullets).

    Shows the first 6 chars (+88017) and the last 3 digits; the 6 middle
    characters are masked.
    """
    if not normalized or not NORMALIZED_REGEX.match(normalized):
        return "•••"
    return normalized[:6] + "••••••" + normalized[-3:]
