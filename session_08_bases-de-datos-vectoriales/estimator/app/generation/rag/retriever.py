"""Semantic retriever — embed a query and rank chunks by cosine similarity.

Thin coordinator over the embedder and the vector store: it keeps the query
embedding (a blocking OpenAI call, run off the event loop) out of the transport
layer. Metadata/access-control filtering and source citations are Session 9+
territory; this only returns the closest chunks.
"""

from __future__ import annotations

from fastapi.concurrency import run_in_threadpool

from app.generation.rag.embedding.embedder import OpenAIEmbedder
from app.generation.rag.store.vector_store import SearchHit, VectorStore


class SemanticRetriever:
    def __init__(self, embedder: OpenAIEmbedder, store: VectorStore) -> None:
        self._embedder = embedder
        self._store = store

    async def retrieve(self, query: str, k: int) -> list[SearchHit]:
        """Embed ``query`` with the same model used at ingest and search top-k."""
        query_vector = await run_in_threadpool(self._embedder.embed_one, query)
        return await self._store.search(query_vector=query_vector, k=k)
