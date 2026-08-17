"""Retrieval pipeline — one entrypoint, four configurations.

:func:`retrieve` is the single door every consumer goes through, and the two
switches behind it define the configurations this session measures:

===========  ==========  =========  ==============================================
Config       Search      Rerank     What it is
===========  ==========  =========  ==============================================
A            vector      no         the Session 9 baseline
B            hybrid      no         + lexical branch, fused by RRF
C            vector      yes        + cross-encoder, recall-then-rerank
D            hybrid      yes        both
===========  ==========  =========  ==============================================

**Recall-then-rerank.** A pattern older than LLMs — web search engines have used
it for decades. The *recall* stage casts a wide net (``recall_k``, e.g. 50); it is
not asked for a fine ordering, only for the relevant document to be somewhere
inside. The *precision* stage scores those pairs jointly with a cross-encoder and
keeps the best few (``rerank_top_n``, e.g. 5). The division of labour is the whole
idea: vector search is excellent at FINDING candidates and mediocre at ORDERING
them, so a second stage does well what the first does badly.

The consequence to keep in mind: **the reranker reorders, it does not retrieve.**
If the relevant budget never entered the recall set, no reranker rescues it — that
is a recall problem, and reranking would just be polishing the order of the wrong
results.

**The asyncio hazard.** Vector search is async (I/O against the database); the
cross-encoder is not (local computation). A few hundred milliseconds of transformer
inference executed directly on the event loop blocks EVERY other request for its
whole duration. The inference is therefore dispatched to a thread with
``asyncio.to_thread``. This does not appear in tutorials; it appears in incident
reports.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.config import get_settings
from app.generation.rag.retrieval.hybrid_search import hybrid_search
from app.generation.rag.retriever import search_chunks
from app.generation.rag.schemas import RetrievalResult

log = structlog.get_logger()

VECTOR = "vector"
HYBRID = "hybrid"


async def retrieve(
    query_embedding: list[float],
    query_text: str,
    *,
    search_mode: str | None = None,
    rerank: bool | None = None,
    top_k: int | None = None,
    recall_k: int | None = None,
    rerank_top_n: int | None = None,
    distance_threshold: float | None = None,
    rrf_k: int | None = None,
    sectors: list[str] | None = None,
    project_year_min: int | None = None,
    project_year_max: int | None = None,
    chunk_types: list[str] | None = None,
    reranker=None,
) -> RetrievalResult:
    """Retrieve chunks through the configured pipeline.

    Every knob resolves the same way: **explicit argument → settings default**.
    Passing nothing runs whatever the deployment is configured for; passing a
    value overrides it for this call only. That is what makes the four
    configurations reproducible from a script without editing code or restarting
    a container.

    Parameters
    ----------
    query_embedding, query_text:
        The same query in the two representations the branches need. ``query_text``
        is required even in ``vector`` mode, because the reranker scores against
        the raw text, not the vector.
    search_mode:
        ``"vector"`` or ``"hybrid"``. Defaults to ``RETRIEVAL_SEARCH_MODE``.
    rerank:
        Whether the cross-encoder stage runs. Defaults to ``RERANKER_ENABLED``.
    top_k:
        Results returned when NOT reranking. Defaults to ``RETRIEVAL_TOP_K``.
    recall_k:
        Width of the recall stage. Defaults to ``RETRIEVAL_RECALL_TOP_K``.
    rerank_top_n:
        Results returned when reranking. Defaults to ``RERANK_TOP_N``.
    distance_threshold, rrf_k:
        Default to ``RETRIEVAL_DISTANCE_THRESHOLD`` and ``RRF_K``.
    sectors, project_year_min, project_year_max, chunk_types:
        Structural filters, forwarded unchanged to every branch.
    reranker:
        Injectable for tests. When ``None`` and reranking is on, the singleton
        comes from the composition root.

    Returns
    -------
    RetrievalResult
        Best first: cross-encoder order when reranking, otherwise distance order
        (vector) or fused order (hybrid). ``low_confidence`` is True only when
        nothing was retrieved at all.

    Raises
    ------
    RetrievalError
        Propagated from the search branches if the store cannot be queried.
    ValueError
        If ``search_mode`` is not a known mode — a typo in configuration must fail
        loudly rather than silently fall back to one of the two branches.
    """
    settings = get_settings()

    search_mode = search_mode if search_mode is not None else settings.RETRIEVAL_SEARCH_MODE
    rerank = rerank if rerank is not None else settings.RERANKER_ENABLED
    top_k = top_k if top_k is not None else settings.RETRIEVAL_TOP_K
    recall_k = recall_k if recall_k is not None else settings.RETRIEVAL_RECALL_TOP_K
    rerank_top_n = rerank_top_n if rerank_top_n is not None else settings.RERANK_TOP_N
    rrf_k = rrf_k if rrf_k is not None else settings.RRF_K
    if distance_threshold is None:
        distance_threshold = settings.RETRIEVAL_DISTANCE_THRESHOLD

    if search_mode not in (VECTOR, HYBRID):
        raise ValueError(f"Unknown search_mode {search_mode!r}; expected {VECTOR!r} or {HYBRID!r}")

    # Recall wide whenever a later stage will re-sort. In the plain vector path
    # with no reranking the recall order IS the final order, so asking for more
    # than top_k would be paying for rows nobody reads.
    recall_width = recall_k if rerank else top_k
    started = time.perf_counter()

    if search_mode == HYBRID:
        result = await hybrid_search(
            query_embedding,
            query_text,
            top_k=recall_width,
            recall_k=recall_k,
            distance_threshold=distance_threshold,
            rrf_k=rrf_k,
            sectors=sectors,
            project_year_min=project_year_min,
            project_year_max=project_year_max,
            chunk_types=chunk_types,
        )
    else:
        result = await search_chunks(
            query_embedding,
            top_k=recall_width,
            distance_threshold=distance_threshold,
            sectors=sectors,
            project_year_min=project_year_min,
            project_year_max=project_year_max,
            chunk_types=chunk_types,
        )

    candidates = result.chunks
    if rerank and candidates:
        if reranker is None:
            from app.dependencies import get_reranker

            reranker = get_reranker()
        # to_thread, NOT a direct call: transformer inference on the event loop
        # would block every concurrent request for its full duration.
        final = await asyncio.to_thread(reranker.rerank, query_text, candidates, top_n=rerank_top_n)
    else:
        final = candidates[:top_k]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "rag_retrieve_done",
        search_mode=search_mode,
        rerank=rerank,
        candidates_in=len(candidates),
        results=len(final),
        recall_k=recall_k if rerank else None,
        top_k=rerank_top_n if rerank else top_k,
        candidates_evaluated=result.candidates_evaluated,
        retrieve_time_ms=elapsed_ms,
    )
    return RetrievalResult(
        chunks=final,
        low_confidence=not final,
        candidates_evaluated=result.candidates_evaluated,
    )
