"""Alembic migration environment.

The DB URL is read from ``app.config.Settings`` (not from alembic.ini) so the
container, the dev host and CI all use the same source of truth. Migrations are
discovered by importing ``app.foundation.persistence.models``: every SQLAlchemy
model in that module is registered against ``Base.metadata`` and becomes visible
to Alembic's autogenerate.

Since Session 8 the environment runs **async** (asyncpg): it derives the async
URL from ``DATABASE_URL`` and registers the pgvector ``vector`` type so that
autogenerate recognises ``Vector`` columns instead of dropping them.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

import pgvector.sqlalchemy
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.foundation.persistence.database_async import async_database_url
from app.foundation.persistence.models import Base  # noqa: F401 — ensure models are imported

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", async_database_url())

target_metadata = Base.metadata


def do_run_migrations(connection) -> None:
    """Configure the context on a live (sync) connection and run migrations."""
    # Teach the dialect about pgvector's ``vector`` type; without this, reflection
    # during autogenerate would not recognise ``Vector`` columns.
    connection.dialect.ischema_names["vector"] = pgvector.sqlalchemy.Vector
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Generate SQL without a live connection — used by ``alembic upgrade --sql``."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against a live async database connection."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
