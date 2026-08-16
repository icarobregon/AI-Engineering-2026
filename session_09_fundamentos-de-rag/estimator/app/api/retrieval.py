"""HTTP layer for the retrieval surface (Session 9).

``POST /v1/retrieval/search`` sits next to the Session 8 ``POST /search``
instead of replacing it: that route is a public contract (ARCHITECTURE.md §8).
The difference is not cosmetic — this one is authenticated, rate-limited, and
exposes the production knobs (distance threshold, structural filters) plus the
``low_confidence`` signal.

Thin as every router here: validation lives in the request model, ranking in
the store, policy in the retriever.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.security import require_retrieval_key
from app.config import get_settings
from app.dependencies import get_semantic_retriever
from app.generation.rag.schemas import RetrievalSearchRequest, RetrievalSearchResponse
from app.generation.rag.retriever import SemanticRetriever
from app.rate_limit import limiter

log = structlog.get_logger()

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


@router.post("/search", response_model=RetrievalSearchResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_RETRIEVAL)
async def search(
    request: Request,  # required by slowapi's decorator
    payload: RetrievalSearchRequest,
    retriever: SemanticRetriever | None = Depends(get_semantic_retriever),
    _key: str = Depends(require_retrieval_key),
) -> RetrievalSearchResponse:
    """Rank the corpus against ``query_text`` under a quality threshold."""
    if retriever is None:
        log.error("retrieval_search_failed", reason="retriever_unavailable")
        raise HTTPException(status_code=503, detail="Embedding service is not available.")

    try:
        result = await retriever.retrieve(
            search_text=payload.query_text,
            top_k=payload.top_k,
            distance_threshold=payload.distance_threshold,
            filters=payload.to_filters(),
        )
    except Exception as exc:  # noqa: BLE001 — embedding/DB failures become a 502.
        log.error(
            "retrieval_search_failed",
            reason="search_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to run semantic search.") from exc

    return RetrievalSearchResponse(
        chunks=result.chunks,
        low_confidence=result.low_confidence,
        total_candidates_considered=result.total_candidates_considered,
        search_time_ms=result.search_time_ms,
    )
