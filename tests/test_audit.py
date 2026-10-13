"""Audit log writer tests (F11.1)."""
from __future__ import annotations

import pytest
from sqlmodel import Session, select

from app.audit import _safe_detail, write_audit
from app.models.audit_log import AuditAction, AuditLog


def test_write_audit_inserts_row(engine):
    with Session(engine) as session:
        write_audit(session, AuditAction.LOGIN_SUCCESS, coordinator_id=1)
        session.commit()
        rows = list(session.exec(select(AuditLog)).all())
    assert len(rows) == 1
    assert rows[0].action == "login_success"
    assert rows[0].coordinator_id == 1


def test_write_audit_truncates_long_detail(engine):
    with Session(engine) as session:
        write_audit(session, AuditAction.DONOR_VERIFY, detail="x" * 1000)
        session.commit()
        row = session.exec(select(AuditLog)).first()
    assert row is not None
    assert row.detail is not None
    assert len(row.detail) <= 500


def test_write_audit_accepts_string_action(engine):
    with Session(engine) as session:
        write_audit(session, "donor_verify", actor_kind="coordinator")
        session.commit()
        row = session.exec(select(AuditLog)).first()
    assert row is not None
    assert row.action == "donor_verify"


# --- PII refusal (F11.1) ---------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "+8801712345678",  # E.164 BD phone
        "01712345678",  # 11-digit BD phone
        "8801712345678",  # 13-digit BD phone
        "phone=01712345678 in audit",
        "1234567890",  # any 10+ digit run
        "abc1234567890123def",  # 13 digits embedded
        "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",  # 32-char hex (token-shaped)
        "chat_id=1234567890",  # telegram chat id
        "user@example.com",  # email
    ],
)
def test_safe_detail_refuses_pii(bad):
    with pytest.raises(ValueError, match="PII-like"):
        _safe_detail(bad)


def test_safe_detail_allows_short_ids():
    # 1-9 digit numbers and short labels are fine.
    assert _safe_detail("area_id=42") == "area_id=42"
    assert _safe_detail("donor_id=7") == "donor_id=7"
    assert _safe_detail("note_set") == "note_set"
    assert _safe_detail(None) is None


def test_safe_detail_truncates_non_pii():
    s = "x" * 1000
    out = _safe_detail(s)
    assert out is not None
    assert len(out) == 500
