"""Database engine and session helpers."""
from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

if TYPE_CHECKING:
    from app.config import Settings


def make_engine(settings: Settings) -> Engine:
    url = settings.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True)


_engine: Engine | None = None


def set_engine(engine: Engine) -> None:
    global _engine
    _engine = engine


def get_engine() -> Engine:
    if _engine is None:
        from app.config import get_settings
        eng = make_engine(get_settings())
        set_engine(eng)
        return eng
    return _engine


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def init_db() -> None:
    """Create tables (used in tests and SQLite dev; Alembic is the source of truth)."""
    from app import models  # noqa: F401  ensure all models are registered
    SQLModel.metadata.create_all(get_engine())
