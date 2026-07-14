"""HTTP layer for semantic search over the persisted chunks.

Thin router: embeds the query, runs a cosine-distance search via the vector store
and maps failures to status codes. No business logic lives here.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_embedder
from app.foundation.persistence.database_async import get_async_session
from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.retriever import SemanticRetriever
from app.generation.rag.schemas import SearchRequest, SearchResponse, SearchResultItem
from app.generation.rag.store.vector_store import VectorStore

log = structlog.get_logger()

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
    session: AsyncSession = Depends(get_async_session),
) -> SearchResponse:
    """Return the ``k`` chunks closest to the query by cosine distance."""
    if embedder is None:
        log.error("search_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="Embedding service is not available.")

    started = time.perf_counter()
    retriever = SemanticRetriever(embedder, VectorStore(session))
    try:
        hits = await retriever.retrieve(request.query, request.k)
    except Exception as exc:  # noqa: BLE001 — any embedding/DB failure becomes a 500.
        log.error(
            "search_failed",
            reason="retrieval_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to run search.") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log.info("search_done", query=request.query, k=request.k, search_time_ms=elapsed_ms)
    return SearchResponse(
        query=request.query,
        k=request.k,
        search_time_ms=elapsed_ms,
        results=[
            SearchResultItem(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                chunk_type=hit.chunk_type,
                content=hit.content,
                distance=hit.distance,
                metadata=hit.metadata,
            )
            for hit in hits
        ],
    )
