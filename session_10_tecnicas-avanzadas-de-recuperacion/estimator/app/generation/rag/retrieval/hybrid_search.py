"""Hybrid search — the semantic and lexical branches, fused by RRF.

Each family has a blind spot the other covers. Semantic search generalises, which
is its virtue and its failure: to an embedding model "Stripe" is approximately a
synonym of "payment gateway", so the budget that integrated *exactly* Stripe
sinks. Lexical search matches literals, so it cannot see that "cobros
recurrentes" and "suscripciones de pago" mean the same thing when they share no
word. In an estimation corpus both query types coexist — often inside the same
query — so the conclusion is not to choose better, it is to stop choosing.

Two design points worth defending:

* **The branches run concurrently.** They are independent I/O against the same
  database, so the cost of hybrid is the SLOWER branch, not the sum. Running them
  sequentially would make the latency column of the measurement look twice as bad
  as the technique actually is.
* **The contract is identical to the vector-only path** — a query goes in, an
  ordered :class:`RetrievalResult` comes out. That uniformity is the point:
  switching from vector to hybrid becomes a configuration change rather than a
  refactor, and comparing them becomes an experiment over one boolean.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from app.generation.rag.retrieval.fulltext_search import search_lexical_chunks
from app.generation.rag.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion
from app.generation.rag.retriever import search_chunks
from app.generation.rag.schemas import RetrievalResult, RetrievedChunk

log = structlog.get_logger()


def _chunk_from_row(row, *, distance: float | None) -> RetrievedChunk:
    """Map a store row onto the typed retrieval contract.

    Same flattening the vector branch does (``client_sector``/``year`` out of
    JSONB). ``distance`` is passed in rather than read off the row because only
    the vector branch produces one.
    """
    return RetrievedChunk(
        id=row.id,
        content=row.content,
        sector=str(row.metadata_.get("client_sector", "unknown")),
        project_year=int(row.metadata_.get("year", 0)),
        chunk_type=row.chunk_type,
        budget_id=row.metadata_.get("budget_id"),
        distance=distance,
    )


async def hybrid_search(
    query_embedding: list[float],
    query_text: str,
    top_k: int = 10,
    recall_k: int = 50,
    distance_threshold: float = 0.6,
    rrf_k: int = DEFAULT_RRF_K,
    sectors: list[str] | None = None,
    project_year_min: int | None = None,
    project_year_max: int | None = None,
    chunk_types: list[str] | None = None,
) -> RetrievalResult:
    """Retrieve with both branches and return a single RRF-fused ranking.

    Parameters
    ----------
    query_embedding:
        Dense query vector for the semantic branch.
    query_text:
        Raw text for the lexical branch. Both describe the same query; they are
        separate arguments because each branch consumes a different
        representation of it.
    top_k:
        How many chunks to return after fusion.
    recall_k:
        Width of each branch before fusion. Wider than ``top_k`` on purpose: this
        is the recall stage, and its only job is to not lose the relevant chunk.
    distance_threshold:
        Relevance floor for the semantic branch (unchanged Session 9 behaviour).
        Note it caps that branch's contribution: chunks beyond the floor never
        enter the fusion, by design — a hybrid pipeline should not resurrect what
        the vector branch already judged irrelevant.
    rrf_k:
        RRF smoothing constant.
    sectors, project_year_min, project_year_max, chunk_types:
        Structural filters, applied identically by both branches.

    Returns
    -------
    RetrievalResult
        ``chunks`` in fused order, truncated to ``top_k``. ``low_confidence`` is
        True only when BOTH branches came back empty — with two branches, one
        finding nothing is a normal outcome, not a failure.

    Raises
    ------
    RetrievalError
        Propagated from either branch if the store cannot be queried.
    """
    started = time.perf_counter()

    # Concurrent, not sequential: hybrid latency is the slower branch.
    semantic_result, lexical_rows = await asyncio.gather(
        search_chunks(
            query_embedding,
            top_k=recall_k,
            distance_threshold=distance_threshold,
            sectors=sectors,
            project_year_min=project_year_min,
            project_year_max=project_year_max,
            chunk_types=chunk_types,
        ),
        search_lexical_chunks(
            query_text,
            top_k=recall_k,
            sectors=sectors,
            project_year_min=project_year_min,
            project_year_max=project_year_max,
            chunk_types=chunk_types,
        ),
    )

    # One pool keyed by chunk id. The semantic branch is inserted first so a chunk
    # found by BOTH keeps its real cosine distance; `setdefault` then leaves
    # lexical-only chunks with distance=None ("never scored by the vector branch")
    # instead of a fabricated value.
    pool: dict[int, RetrievedChunk] = {chunk.id: chunk for chunk in semantic_result.chunks}
    for row in lexical_rows:
        pool.setdefault(row.id, _chunk_from_row(row, distance=None))

    fused = reciprocal_rank_fusion(
        [
            [chunk.id for chunk in semantic_result.chunks],
            [row.id for row in lexical_rows],
        ],
        k=rrf_k,
    )
    chunks = [pool[chunk_id] for chunk_id, _score in fused[:top_k]]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "rag_hybrid_search_done",
        semantic_hits=len(semantic_result.chunks),
        lexical_hits=len(lexical_rows),
        # How much the two branches actually disagreed. If this is ~0 the fusion
        # is not earning its latency on this corpus; if it is high, RRF has real
        # consensus signal to work with. Cheap to log, expensive to reconstruct.
        pool_size=len(pool),
        results=len(chunks),
        top_k=top_k,
        recall_k=recall_k,
        rrf_k=rrf_k,
        search_time_ms=elapsed_ms,
    )
    return RetrievalResult(
        chunks=chunks,
        low_confidence=not chunks,
        candidates_evaluated=semantic_result.candidates_evaluated,
    )
