"""Migration upgrade/downgrade tests (A2)."""
from __future__ import annotations

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


@pytest.fixture
def alembic_cfg(tmp_path):  # type: ignore[no-untyped-def]
    cfg = Config("alembic.ini")
    db_path = tmp_path / "bloodlink.db"
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_upgrade_creates_all_tables(alembic_cfg, tmp_path):
    db_path = tmp_path / "bloodlink.db"
    command.upgrade(alembic_cfg, "head")
    eng = create_engine(f"sqlite:///{db_path}")
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    expected = {
        "coordinators",
        "areas",
        "donors",
        "requests",
        "contact_attempts",
        "audit_log",
        "login_attempts",
        "request_attempts",
        "telegram_links",
    }
    assert expected.issubset(names), f"missing tables: {expected - names}"


def test_downgrade_drops_all_tables(alembic_cfg, tmp_path):
    db_path = tmp_path / "bloodlink.db"
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    eng = create_engine(f"sqlite:///{db_path}")
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    # After downgrade to base, only the alembic_version table remains.
    assert "donors" not in names
    assert "requests" not in names


def test_upgrade_then_downgrade_is_idempotent(alembic_cfg, tmp_path):
    db_path = tmp_path / "bloodlink.db"
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    eng = create_engine(f"sqlite:///{db_path}")
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    assert "donors" in names
    assert "requests" in names
