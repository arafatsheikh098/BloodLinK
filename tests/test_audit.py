"""Audit log writer tests (F11.1)."""
from __future__ import annotations

from sqlmodel import Session, select

from app.audit import write_audit
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