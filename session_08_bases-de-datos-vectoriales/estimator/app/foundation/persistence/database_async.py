"""Async SQLAlchemy engine and session — the Session 8 vector layer.

The Session 6 persistence (``database.py``) is deliberately *synchronous* because
it runs off the hot request path (BackgroundTasks). The vector layer added in
Session 8 (``documents``/``chunks`` + ``POST /embeddings/ingest`` + ``POST
/search``) is on the request path, so it uses the *async* SQLAlchemy API with the
``asyncpg`` driver.

Both stacks talk to the same database. There is a single source of truth for the
URL — ``Settings.DATABASE_URL`` (the sync ``+psycopg`` form) — from which the
async URL is derived by swapping the driver. That keeps ``.env``/compose
unchanged while giving the async engine the driver it needs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def async_database_url() -> str:
    """Derive the asyncpg URL from the sync ``DATABASE_URL`` (single source)."""
    return get_settings().DATABASE_URL.replace("+psycopg", "+asyncpg")


@lru_cache
def create_async_engine_from_settings() -> AsyncEngine:
    """Build the global async engine (singleton)."""
    return create_async_engine(async_database_url(), pool_pre_ping=True)


AsyncSessionLocal = async_sessionmaker(
    bind=create_async_engine_from_settings(),
    autoflush=False,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields an AsyncSession and closes it on exit."""
    async with AsyncSessionLocal() as session:
        yield session
