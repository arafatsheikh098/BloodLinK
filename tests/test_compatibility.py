"""Tests for the blood compatibility table (F7.1, F7.2)."""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.compatibility import (
    ALL_GROUPS,
    DONOR_COMPATIBILITY,
    all_compatible_donor_groups,
    can_donate_to,
    is_rh_negative,
    is_rh_positive,
)

# F7.1: full hand-written 8x8 table is correct -----------------------------


def test_compatibility_table_is_total():
    """Every donor group must have an entry covering all 8 recipient groups
    (or a subset thereof)."""
    for g in ALL_GROUPS:
        assert g in DONOR_COMPATIBILITY
        for r in ALL_GROUPS:
            # type assertion: result of `in` is bool
            assert isinstance(can_donate_to(g, r), bool)


def test_o_negative_is_universal_donor():
    for r in ALL_GROUPS:
        assert can_donate_to("O-", r) is True


def test_ab_positive_is_universal_recipient():
    for g in ALL_GROUPS:
        assert can_donate_to(g, "AB+") is True


def test_o_positive_donates_only_to_positive():
    for r in ALL_GROUPS:
        if is_rh_positive(r):
            assert can_donate_to("O+", r) is True
        else:
            assert can_donate_to("O+", r) is False


def test_a_negative_donates_to_a_and_ab():
    for r in ALL_GROUPS:
        if r.startswith("A") or r.startswith("AB"):
            assert can_donate_to("A-", r) is True
        else:
            assert can_donate_to("A-", r) is False


def test_a_positive_donates_only_to_a_plus_ab_plus():
    for r in ALL_GROUPS:
        if r in ("A+", "AB+"):
            assert can_donate_to("A+", r) is True
        else:
            assert can_donate_to("A+", r) is False


def test_b_negative_donates_to_b_and_ab():
    for r in ALL_GROUPS:
        if r.startswith("B") or r.startswith("AB"):
            assert can_donate_to("B-", r) is True
        else:
            assert can_donate_to("B-", r) is False


def test_b_positive_donates_only_to_b_plus_ab_plus():
    for r in ALL_GROUPS:
        if r in ("B+", "AB+"):
            assert can_donate_to("B+", r) is True
        else:
            assert can_donate_to("B+", r) is False


def test_ab_negative_donates_only_to_ab():
    for r in ALL_GROUPS:
        if r.startswith("AB"):
            assert can_donate_to("AB-", r) is True
        else:
            assert can_donate_to("AB-", r) is False


def test_ab_positive_donates_only_to_ab_positive():
    for r in ALL_GROUPS:
        if r == "AB+":
            assert can_donate_to("AB+", r) is True
        else:
            assert can_donate_to("AB+", r) is False


# F7.2: Rh- recipient NEVER receives from Rh+ donor -------------------------


@pytest.mark.parametrize(
    "donor_group",
    [g for g in ALL_GROUPS if is_rh_positive(g)],
)
@pytest.mark.parametrize(
    "recipient_group",
    [g for g in ALL_GROUPS if is_rh_negative(g)],
)
def test_rh_negative_recipient_never_gets_rh_positive(donor_group, recipient_group):
    assert can_donate_to(donor_group, recipient_group) is False


def test_all_compatible_donor_groups_helper():
    # AB+ recipients accept from all 8 donor groups
    donors = all_compatible_donor_groups("AB+")
    assert sorted(donors) == sorted(ALL_GROUPS)
    # O+ recipients accept from O- and O+ only
    donors_o = all_compatible_donor_groups("O+")
    assert sorted(donors_o) == sorted(["O-", "O+"])
    # A+ recipients accept from O-, O+, A-, A+
    donors_a = all_compatible_donor_groups("A+")
    assert sorted(donors_a) == sorted(["O-", "O+", "A-", "A+"])
    # AB- recipients accept from O-, A-, B-, AB-
    donors_abn = all_compatible_donor_groups("AB-")
    assert sorted(donors_abn) == sorted(["O-", "A-", "B-", "AB-"])


def test_can_donate_to_unknown_group_returns_false():
    assert can_donate_to("X+", "A+") is False
    assert can_donate_to("A+", "X+") is False


# Property: if a donor can give to X, and X can give to Y (per AB+), then... no,
# we just check the explicit table is internally consistent via the helper.


@given(
    donor=st.sampled_from(ALL_GROUPS),
    recipient=st.sampled_from(ALL_GROUPS),
)
def test_can_donate_to_is_pure_function(donor, recipient):
    """`can_donate_to` must always return a stable boolean for the same args."""
    a = can_donate_to(donor, recipient)
    b = can_donate_to(donor, recipient)
    assert a == b
    assert isinstance(a, bool)


def test_is_rh_helpers():
    assert is_rh_negative("O-") is True
    assert is_rh_negative("A+") is False
    assert is_rh_positive("AB+") is True
    assert is_rh_positive("B-") is False
