"""Lexical branch of hybrid search — keyword retrieval over ``content_tsv``.

Mirrors :func:`app.generation.rag.retriever.search_chunks` deliberately: same
structural filters, same composition-root wiring, same error wrapping, same
structured logging. The two branches are interchangeable inputs to fusion, and
keeping their shape identical is what lets the pipeline treat "vector" and
"hybrid" as one switch instead of two code paths.

It returns rows rather than :class:`RetrievedChunk` objects because the caller
that fuses is the one that decides what a final chunk looks like — a chunk found
by both branches carries a real cosine distance, and one found only here carries
none. Building the typed objects here would force this module to invent that
missing distance.
"""

from __future__ import annotations

import time

import structlog
from sqlalchemy import Row

from app.generation.rag.errors import RetrievalError

log = structlog.get_logger()


async def search_lexical_chunks(
    query_text: str,
    top_k: int = 50,
    sectors: list[str] | None = None,
    project_year_min: int | None = None,
    project_year_max: int | None = None,
    chunk_types: list[str] | None = None,
) -> list[Row]:
    """Run the keyword branch and return its ranking, best first.

    Parameters
    ----------
    query_text:
        Raw query text — the lexical branch works on the words themselves, so
        unlike the vector branch it takes text and not an embedding.
    top_k:
        Recall width for this branch (default 50).
    sectors, project_year_min, project_year_max, chunk_types:
        Structural filters, identical in meaning to the vector branch.

    Returns
    -------
    list[Row]
        Rows ordered by descending ``lexical_rank``. Empty when the query reduces
        to an empty tsquery or nothing matches — a normal outcome for a purely
        conceptual query with no literal overlap, NOT an error.

    Raises
    ------
    RetrievalError
        If the store cannot be queried.
    """
    from app.dependencies import get_async_session_factory, get_chunk_store

    session_factory = get_async_session_factory()
    store = get_chunk_store()

    started = time.perf_counter()
    try:
        async with session_factory() as session:
            rows = await store.search_lexical(
                session,
                query_text=query_text,
                top_k=top_k,
                sectors=sectors,
                project_year_min=project_year_min,
                project_year_max=project_year_max,
                chunk_types=chunk_types,
            )
    except Exception as exc:  # noqa: BLE001 — DB/connection failure.
        log.error("rag_lexical_search_failed", error_type=type(exc).__name__, error=str(exc)[:200])
        raise RetrievalError("Lexical store query failed.") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "rag_lexical_search_done",
        query=query_text[:80],
        results=len(rows),
        top_k=top_k,
        search_time_ms=elapsed_ms,
    )
    return rows
