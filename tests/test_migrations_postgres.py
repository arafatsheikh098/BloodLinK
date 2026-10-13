"""Postgres migration test (skipped unless DATABASE_URL is Postgres)."""
from __future__ import annotations

import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgres"),
    reason="DATABASE_URL is not Postgres",
)
def test_postgres_upgrade_and_downgrade():
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")
    eng = create_engine(os.environ["DATABASE_URL"])
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    assert "donors" in names
    assert "requests" in names
    command.downgrade(cfg, "base")
    eng = create_engine(os.environ["DATABASE_URL"])
    try:
        names = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    assert "donors" not in names
