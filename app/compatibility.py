"""Blood compatibility table for red-cell transfusion (F7.1, F7.2).

We model compatibility as a function donor -> set of recipient groups.
The full 8x8 table is hand-written here and asserted by an exhaustive test.
"""
from __future__ import annotations

# All 8 blood groups.
ALL_GROUPS: tuple[str, ...] = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")


# For each donor blood group, the set of recipient groups the donor can give to.
# Standard red-cell rules:
#   O-  -> everyone
#   O+  -> O+, A+, B+, AB+
#   A-  -> A-, A+, AB-, AB+
#   A+  -> A+, AB+
#   B-  -> B-, B+, AB-, AB+
#   B+  -> B+, AB+
#   AB- -> AB-, AB+
#   AB+ -> AB+
DONOR_COMPATIBILITY: dict[str, frozenset[str]] = {
    "O-": frozenset({"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"}),
    "O+": frozenset({"O+", "A+", "B+", "AB+"}),
    "A-": frozenset({"A-", "A+", "AB-", "AB+"}),
    "A+": frozenset({"A+", "AB+"}),
    "B-": frozenset({"B-", "B+", "AB-", "AB+"}),
    "B+": frozenset({"B+", "AB+"}),
    "AB-": frozenset({"AB-", "AB+"}),
    "AB+": frozenset({"AB+"}),
}


def can_donate_to(donor_group: str, recipient_group: str) -> bool:
    """Return True if a donor with `donor_group` can donate to `recipient_group`.

    Rh- recipients never receive from Rh+ donors. Both the donor table and this
    helper satisfy that property (asserted in test_compatibility.py).
    """
    recipients = DONOR_COMPATIBILITY.get(donor_group)
    if recipients is None:
        return False
    return recipient_group in recipients


def all_compatible_donor_groups(recipient_group: str) -> list[str]:
    """Return the list of donor groups compatible with `recipient_group`, in
    the canonical order. Useful for the exhaustive test."""
    return [g for g in ALL_GROUPS if can_donate_to(g, recipient_group)]


def is_rh_negative(blood_group: str) -> bool:
    return blood_group.endswith("-")


def is_rh_positive(blood_group: str) -> bool:
    return blood_group.endswith("+")
