"""Phone normalization tests (F2.2, F2.3)."""
from __future__ import annotations

import pytest

from app.phone import (
    NORMALIZED_REGEX,
    PhoneNormalizationError,
    is_valid_bd_mobile,
    mask_phone,
    normalize_bd_mobile,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01712345678", "+8801712345678"),
        ("+8801712345678", "+8801712345678"),
        ("8801712345678", "+8801712345678"),
        ("017-1234-5678", "+8801712345678"),
        ("+880 1712 345 678", "+8801712345678"),
        ("+880 (1712) 345-678", "+8801712345678"),
    ],
)
def test_accepts_all_supported_forms(raw, expected):
    assert normalize_bd_mobile(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "01212345678",  # operator digit 2 invalid
        "01012345678",  # operator digit 0 invalid
        "01112345678",  # operator digit 1 invalid (not assigned)
        "01712345",  # too short
        "0171234567890123",  # too long
        "+88021234567",  # too short
        "02-1234567",  # landline
        "abcdefghij",  # garbage
        "",  # empty
        "+1-202-555-0143",  # US number
    ],
)
def test_rejects_invalid_forms(raw):
    with pytest.raises(PhoneNormalizationError):
        normalize_bd_mobile(raw)


def test_is_valid_helper():
    assert is_valid_bd_mobile("01712345678")
    assert not is_valid_bd_mobile("01212345678")
    assert not is_valid_bd_mobile("")


def test_normalized_form_matches_regex():
    n = normalize_bd_mobile("01712345678")
    assert NORMALIZED_REGEX.match(n)


def test_mask_phone():
    assert mask_phone("+8801712345678") == "+88017••••••678"
    assert mask_phone("not a number") == "•••"


def test_specific_invalid_examples():
    # Operator-digit rejections
    for bad in ("012", "010", "011"):
        with pytest.raises(PhoneNormalizationError):
            normalize_bd_mobile(f"{bad}12345678")
