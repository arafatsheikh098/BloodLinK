"""Pytest fixtures shared across the test suite.

We use a fresh in-memory SQLite database for each test session and re-apply
the SQLModel metadata to keep things fast and isolated.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool
from sqlmodel import Session, SQLModel, create_engine

# Configure env BEFORE importing the app.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
os.environ.setdefault("ENV", "test")
os.environ.setdefault("DEMO_MODE", "false")

from app import create_app as _create_app  # noqa: E402
from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_settings() -> Iterator[None]:
    """Reset the settings cache between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def temp_db() -> Iterator[str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield f"sqlite:///{path}"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def engine(temp_db: str):  # type: ignore[no-untyped-def]
    eng = create_engine(
        temp_db,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine) -> Iterator[Session]:  # type: ignore[no-untyped-def]
    with Session(engine) as session:
        yield session


@pytest.fixture
def app_client(temp_db: str, monkeypatch) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    # Point the app at a fresh SQLite DB.
    monkeypatch.setenv("DATABASE_URL", temp_db)
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-production-use-only-ci")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()

    eng = create_engine(
        temp_db,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    app_db.set_engine(eng)
    SQLModel.metadata.create_all(eng)

    application = _create_app()
    with TestClient(application, follow_redirects=False) as client:
        yield client
    eng.dispose()
