"""The checkpointer: the graph's state, persisted after every node.

It runs on the PROJECT's Postgres — the same pgvector instance the embeddings
live in. The checkpointer creates its own tables (``checkpoints``,
``checkpoint_writes``, ``checkpoint_blobs``) and coexists with them; standing up
a second database for this would be infrastructure nobody asked for.

Two details that bite:

* ``setup()`` has to run once or the first execution fails on missing tables.
* ``DATABASE_URL`` is a SQLAlchemy URL (``postgresql+psycopg://``). psycopg's
  pool wants a plain libpq conninfo, so the dialect suffix is stripped here
  rather than duplicating the URL in the environment.
* Opening the pool is BOUNDED, and it is preceded by a single probe connection.
  Without one, a Postgres that is down costs the pool's whole retry window on
  every startup — including every test that runs the app's lifespan — while a
  refused connection is known in milliseconds. Startup should learn it that fast
  and degrade, not wait to be told what it could have asked.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

log = structlog.get_logger()


def to_libpq_conninfo(database_url: str, *, connect_timeout: int = 5) -> str:
    """Turn a SQLAlchemy URL into something psycopg accepts.

    The libpq-level ``connect_timeout`` is what stops a single unreachable host
    from blocking for the OS default (minutes) before the pool's own timeout can
    even be considered.
    """
    conninfo = re.sub(r"^postgresql\+\w+://", "postgresql://", database_url)
    if "connect_timeout=" in conninfo:
        return conninfo
    separator = "&" if "?" in conninfo else "?"
    return f"{conninfo}{separator}connect_timeout={connect_timeout}"


@asynccontextmanager
async def open_checkpointer(
    database_url: str, *, max_size: int = 10, timeout: float = 5.0, connect_timeout: int = 3
):
    """Yield a ready ``AsyncPostgresSaver``, closing its pool on the way out.

    Async, not sync: this stack is FastAPI + asyncpg, and the synchronous saver
    would block the event loop on every checkpoint write — one per node.
    """
    conninfo = to_libpq_conninfo(database_url, connect_timeout=connect_timeout)
    # Probe first: this raises at once when nothing is listening, where the pool
    # would keep retrying until its own timeout expired.
    probe = await AsyncConnection.connect(conninfo)
    await probe.close()

    pool = AsyncConnectionPool(
        conninfo=conninfo,
        # One connection is enough to prove the database is there; the rest are
        # created on demand. Opening four up front only makes an unreachable
        # host four times as slow to give up on.
        min_size=1,
        max_size=max_size,
        open=False,
        # The saver runs its own transactions; autocommit is what its own docs
        # expect from the pool it is handed.
        kwargs={"autocommit": True, "row_factory": None},
    )
    # wait=True + timeout: prove the database is actually reachable here, so an
    # unreachable one raises now instead of surfacing on the first estimate.
    await pool.open(wait=True, timeout=timeout)
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        log.info("graph_checkpointer_ready", backend="postgres")
        yield checkpointer
    finally:
        await pool.close()
