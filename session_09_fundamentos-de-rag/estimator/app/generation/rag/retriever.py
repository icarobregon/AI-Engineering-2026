"""Semantic retriever over the pgvector store (Session 8).

Embeds the query with the SAME model used at ingest time (mixing embedding
models makes distances meaningless) and ranks chunks by cosine distance via
SQL. No vector index and no metadata filtering yet — both are built live in
the session on top of this baseline.
"""

from __future__ import annotations

import asyncio
import time

import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.schemas import (
    RetrievalFilters,
    RetrievalResult,
    RetrievedChunk,
    SearchHit,
    SearchResponse,
)
from app.generation.rag.store.repository import ChunkStore

log = structlog.get_logger()


class SemanticRetriever:
    """k-NN retrieval: embed the query, rank chunks by cosine distance."""

    def __init__(
        self,
        embedder: OpenAIEmbedder,
        session_factory: async_sessionmaker,
        store: ChunkStore,
    ) -> None:
        self._embedder = embedder
        self._session_factory = session_factory
        self._store = store

    async def search(self, *, query: str, k: int) -> SearchResponse:
        started = time.perf_counter()

        # Sync OpenAI client → thread, same reasoning as in the ingest path.
        query_vector = await asyncio.to_thread(self._embedder.embed_one, query)

        async with self._session_factory() as session:
            rows = await self._store.search(session, query_vector=query_vector, k=k)

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response = SearchResponse(
            query=query,
            k=k,
            search_time_ms=elapsed_ms,
            results=[
                SearchHit(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    chunk_type=row.chunk_type,
                    content=row.content,
                    distance=float(row.distance),
                    metadata=row.metadata_,
                )
                for row in rows
            ],
        )
        log.info(
            "rag_search_done",
            query=query[:80],
            k=k,
            results=len(response.results),
            search_time_ms=elapsed_ms,
        )
        return response

    async def retrieve(
        self,
        *,
        search_text: str,
        top_k: int,
        distance_threshold: float,
        filters: RetrievalFilters | None = None,
        post_filtering: bool = False,
        wide_k_factor: int = 3,
    ) -> RetrievalResult:
        """Session 9 retrieval: top-K + quality threshold + structural filters.

        Returns :class:`RetrievalResult` rather than a bare list because the
        empty case carries information the caller must act on. ``low_confidence
        = True`` with zero chunks means "the corpus has nothing close enough to
        this project", and the orchestrator is required to stop there instead
        of asking the model to estimate from an empty context. Silently
        generating from nothing is how a RAG system starts inventing numbers
        that look exactly like the grounded ones.
        """
        filters = filters or RetrievalFilters()
        started = time.perf_counter()

        query_vector = await asyncio.to_thread(self._embedder.embed_one, search_text)

        async with self._session_factory() as session:
            total_candidates = await self._store.count_candidates(session, filters=filters)
            if post_filtering:
                rows = await self._store.search_wide_then_filter(
                    session,
                    query_vector=query_vector,
                    top_k=top_k,
                    distance_threshold=distance_threshold,
                    filters=filters,
                    wide_k=top_k * wide_k_factor,
                )
            else:
                rows = await self._store.search_filtered(
                    session,
                    query_vector=query_vector,
                    top_k=top_k,
                    distance_threshold=distance_threshold,
                    filters=filters,
                )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        chunks = [RetrievedChunk.from_row(row) for row in rows]
        result = RetrievalResult(
            chunks=chunks,
            low_confidence=not chunks,
            total_candidates_considered=total_candidates,
            search_time_ms=elapsed_ms,
        )
        log.info(
            "rag_retrieval_done",
            search_text=search_text[:120],
            top_k=top_k,
            distance_threshold=distance_threshold,
            filters=filters.model_dump(exclude_none=True),
            strategy="post_filtering" if post_filtering else "pre_filtering",
            results=len(chunks),
            best_distance=round(chunks[0].distance, 4) if chunks else None,
            worst_distance=round(chunks[-1].distance, 4) if chunks else None,
            total_candidates_considered=total_candidates,
            low_confidence=result.low_confidence,
            search_time_ms=elapsed_ms,
        )
        return result
