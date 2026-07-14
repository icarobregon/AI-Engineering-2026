"""HTTP layer for the embedding pipeline.

Thin router: it orchestrates chunker -> embedder -> response assembly and maps
failures to status codes. No business logic lives here.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ALL_STRATEGIES, build_chunkers, get_chunker, get_embedder
from app.foundation.persistence.database_async import get_async_session
from app.generation.rag.chunking.structural import JSONStructuralChunker
from app.generation.rag.analysis.comparison import (
    ChunkingComparator,
    CompareRequest,
    CompareResponse,
)
from app.generation.rag.embedding.embedder import EMBEDDING_DIM, OpenAIEmbedder
from app.generation.rag.schemas import (
    Budget,
    IngestDocumentRequest,
    IngestDocumentResponse,
)
from app.generation.rag.store.vector_store import DocumentAlreadyExists, VectorStore

log = structlog.get_logger()

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


def _document_metadata(budget: Budget) -> dict:
    """Document-level, filterable metadata derived from the budget header."""
    return {
        "budget_id": budget.budget_id,
        "client_name": budget.client_metadata.name,
        "client_sector": budget.client_metadata.sector,
        "client_country": budget.client_metadata.country,
        "project_summary": budget.project_summary,
        "main_technology": budget.main_technology,
        "year": budget.year,
        "total_estimated_hours": budget.total_estimated_hours,
    }


@router.post("/ingest", response_model=IngestDocumentResponse)
async def ingest(
    request: IngestDocumentRequest,
    chunker: JSONStructuralChunker = Depends(get_chunker),
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
    session: AsyncSession = Depends(get_async_session),
) -> IngestDocumentResponse:
    """Persist one budget as a document + its embedded chunks in a transaction."""
    if embedder is None:
        # No OPENAI_API_KEY configured. Generic message to the client, detail logged.
        log.error("embeddings_ingest_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="Embedding service is not available.")

    started = time.perf_counter()
    budget = request.content
    chunks = chunker.chunk([budget])
    log.info(
        "embeddings_ingest_received",
        source_path=request.source_path,
        budget_id=budget.budget_id,
        total_chunks=len(chunks),
    )

    try:
        embedded = await run_in_threadpool(embedder.embed_many, chunks)
    except Exception as exc:  # noqa: BLE001 — any embedding-API failure becomes a 500.
        log.error(
            "embeddings_ingest_failed",
            reason="embedding_api_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to generate embeddings.") from exc

    store = VectorStore(session)
    try:
        document_id, chunks_created = await store.ingest_document(
            source_path=request.source_path,
            document_type=request.document_type,
            doc_metadata=_document_metadata(budget),
            chunks=embedded,
        )
    except DocumentAlreadyExists as exc:
        # Flat body (not HTTPException, which would nest under "detail") to match
        # the documented contract: {"detail": ..., "document_id": ...}.
        return JSONResponse(
            status_code=409,
            content={"detail": "Document already ingested", "document_id": exc.document_id},
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log.info(
        "embeddings_ingest_done",
        document_id=document_id,
        chunks_created=chunks_created,
        ingestion_time_ms=elapsed_ms,
    )
    return IngestDocumentResponse(
        document_id=document_id,
        chunks_created=chunks_created,
        embedding_dimension=EMBEDDING_DIM,
        ingestion_time_ms=elapsed_ms,
    )


@router.post("/compare", response_model=CompareResponse)
def compare(
    request: CompareRequest,
    embedder: OpenAIEmbedder | None = Depends(get_embedder),
) -> CompareResponse:
    """Run several chunking strategies over the same budgets and compare them.

    Returns per-strategy corpus stats and, if queries are given, the top-k
    chunks each strategy retrieves. Nothing is persisted (Session 8 territory).
    """
    if embedder is None:
        log.error("embeddings_compare_failed", reason="embedder_unavailable")
        raise HTTPException(status_code=500, detail="Embedding service is not available.")

    names = request.strategies or ALL_STRATEGIES
    try:
        chunkers = build_chunkers(names)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown strategy: {exc.args[0]}") from exc
    except RuntimeError as exc:
        # A strategy needs an API key that is not configured.
        log.error("embeddings_compare_failed", reason="missing_api_key", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    comparator = ChunkingComparator(chunkers, embedder)
    log.info(
        "embeddings_compare_received",
        total_budgets=len(request.budgets),
        strategies=names,
        n_queries=len(request.queries),
    )
    try:
        stats = comparator.compute_stats(request.budgets)
        queries = comparator.run_queries(request.budgets, request.queries, request.top_k)
    except Exception as exc:  # noqa: BLE001 — any chunker/embedding failure becomes a 500.
        log.error(
            "embeddings_compare_failed",
            reason="comparison_error",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=500, detail="Failed to run chunking comparison.") from exc

    return CompareResponse(stats_per_strategy=stats, queries_per_strategy=queries)
