"""POST /embeddings/ingest — chunk budgets and return their vectors.

Thin HTTP layer: it orchestrates ``chunker.chunk()`` then ``embedder.embed_many()``
and assembles aggregate stats. Nothing is persisted (Session 8 adds pgvector).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_chunker, get_embedder
from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.embedder import COST_PER_MILLION_TOKENS_USD, OpenAIEmbedder
from app.embedding_pipeline.schemas import (
    IngestRequest,
    IngestResponse,
    IngestStats,
)

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(
    request: IngestRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
) -> IngestResponse:
    if embedder is None:
        raise HTTPException(
            status_code=503,
            detail="Embeddings unavailable: OPENAI_API_KEY is not configured.",
        )

    budgets = request.root
    chunks = chunker.chunk(budgets)

    try:
        embedded = embedder.embed_many(chunks)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "embeddings_ingest_failed",
            error=str(exc)[:400],
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=500, detail="Failed to generate embeddings.")

    total_tokens = sum(c.token_count for c in chunks)
    stats = IngestStats(
        total_budgets=len(budgets),
        total_chunks=len(embedded),
        total_tokens=total_tokens,
        estimated_cost_usd=total_tokens * COST_PER_MILLION_TOKENS_USD / 1_000_000,
    )
    log.info(
        "embeddings_ingest_completed",
        total_budgets=stats.total_budgets,
        total_chunks=stats.total_chunks,
        total_tokens=stats.total_tokens,
    )
    return IngestResponse(chunks=embedded, stats=stats)
