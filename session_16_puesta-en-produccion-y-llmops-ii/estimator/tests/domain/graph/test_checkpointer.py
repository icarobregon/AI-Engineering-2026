"""The checkpointer's two responsibilities that do not need a database.

Both are the kind of thing that only shows up in production: a URL the driver
silently refuses, and a database that is down turning startup into a hang.
"""

from __future__ import annotations

import time

import pytest

from app.domain.graph.checkpointer import open_checkpointer, to_libpq_conninfo


def test_the_sqlalchemy_dialect_is_stripped_for_psycopg():
    # DATABASE_URL is written for SQLAlchemy; psycopg's pool rejects the
    # "+psycopg" dialect suffix outright. Rewriting it here beats carrying the
    # same connection string twice in the environment.
    conninfo = to_libpq_conninfo("postgresql+psycopg://user:pw@db:5432/estimator")
    assert conninfo.startswith("postgresql://user:pw@db:5432/estimator")
    assert "+psycopg" not in conninfo


def test_a_connect_timeout_is_always_present():
    assert "connect_timeout=5" in to_libpq_conninfo("postgresql://db/x", connect_timeout=5)


def test_an_existing_connect_timeout_is_respected():
    given = "postgresql://db/x?connect_timeout=30"
    assert to_libpq_conninfo(given) == given


def test_a_query_string_is_extended_not_replaced():
    conninfo = to_libpq_conninfo("postgresql://db/x?sslmode=require", connect_timeout=4)
    assert "sslmode=require" in conninfo and "connect_timeout=4" in conninfo


async def test_an_unreachable_database_fails_fast_instead_of_hanging():
    """Startup degrades from an exception; it cannot degrade from a wait.

    Port 1 has nothing listening, so this is the "Postgres is down" path. It has
    to be quick: the app's lifespan opens the checkpointer, and every test that
    starts the app pays whatever this costs.
    """
    started = time.perf_counter()
    with pytest.raises(Exception):
        async with open_checkpointer("postgresql+psycopg://u:p@127.0.0.1:1/db", timeout=2.0):
            pass
    assert time.perf_counter() - started < 2.0
