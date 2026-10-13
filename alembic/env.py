"""Alembic environment.

Reads DATABASE_URL from the app's settings so the migration is driven by the
same env vars as the app.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app import models  # noqa: F401
from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Resolve the database URL in this order:
#   1. The URL already on the alembic Config (e.g. set by tests / `alembic -x`).
#      We treat it as "set" when it differs from the alembic.ini default.
#   2. The app's settings (which reads DATABASE_URL env var).
ini_url = config.get_main_option("sqlalchemy.url")
ini_default = "sqlite:///./bloodlink.db"
if ini_url and ini_url != ini_default:
    db_url = ini_url
else:
    db_url = settings.database_url
config.set_main_option("sqlalchemy.url", db_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
