"""CLI tests (F1.6, F1.7)."""
from __future__ import annotations

import pytest
from sqlalchemy import StaticPool
from sqlmodel import Session, SQLModel, select

from app.cli import main as cli_main
from app.config import get_settings
from app.models.coordinator import Coordinator


def test_create_coordinator_creates_row(temp_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", temp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
    monkeypatch.setenv("ENV", "test")
    get_settings.cache_clear()

    from sqlmodel import create_engine as ce

    from app import db as app_db

    eng = ce(temp_db, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    app_db.set_engine(eng)
    SQLModel.metadata.create_all(eng)

    rc = cli_main(["create-coordinator", "alice", "secret123"])
    assert rc == 0

    with Session(eng) as session:
        rows = list(session.exec(select(Coordinator)).all())
    assert len(rows) == 1
    assert rows[0].username == "alice"
    assert rows[0].password_hash != "secret123"  # hashed
    eng.dispose()


def test_create_coordinator_refuses_duplicate(temp_db, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", temp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
    monkeypatch.setenv("ENV", "test")
    get_settings.cache_clear()

    from sqlmodel import create_engine as ce

    from app import db as app_db

    eng = ce(temp_db, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    app_db.set_engine(eng)
    SQLModel.metadata.create_all(eng)

    cli_main(["create-coordinator", "alice", "secret123"])
    rc = cli_main(["create-coordinator", "alice", "different"])
    assert rc == 1  # already exists
    eng.dispose()


def test_default_secret_refused_in_production(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    from app.config import DEFAULT_SECRET_KEY, Settings

    s = Settings(_env_file=None, env="production", secret_key=DEFAULT_SECRET_KEY)
    with pytest.raises(RuntimeError):
        s.validate_production()


def test_custom_secret_accepted_in_production(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    from app.config import Settings

    s = Settings(_env_file=None, env="production", secret_key="a-real-random-32-byte-hex")
    s.validate_production()  # no raise


def test_seed_coordinator_via_cli(temp_db, monkeypatch):
    """F1.7: the create-coordinator CLI is the supported way to seed the
    first coordinator. (Auto-seed at app start was removed because it ran
    before migrations on a fresh install.)
    """
    monkeypatch.setenv("DATABASE_URL", temp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
    monkeypatch.setenv("ENV", "test")
    get_settings.cache_clear()

    from sqlmodel import create_engine as ce

    from app import db as app_db

    eng = ce(temp_db, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    app_db.set_engine(eng)
    SQLModel.metadata.create_all(eng)

    rc = cli_main(["create-coordinator", "bootuser", "bootpass"])
    assert rc == 0
    with Session(eng) as session:
        rows = list(session.exec(select(Coordinator)).all())
    assert any(r.username == "bootuser" for r in rows)
    eng.dispose()


def test_create_app_does_not_seed(temp_db, monkeypatch):
    """create_app() must NOT auto-create coordinators (would run before
    migrations on a fresh install)."""
    monkeypatch.setenv("DATABASE_URL", temp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.delenv("SEED_COORDINATOR_USERNAME", raising=False)
    monkeypatch.delenv("SEED_COORDINATOR_PASSWORD", raising=False)
    get_settings.cache_clear()

    from sqlmodel import create_engine as ce

    from app import create_app
    from app import db as app_db

    eng = ce(temp_db, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    app_db.set_engine(eng)
    SQLModel.metadata.create_all(eng)

    create_app()
    with Session(eng) as session:
        rows = list(session.exec(select(Coordinator)).all())
    assert rows == []
    eng.dispose()