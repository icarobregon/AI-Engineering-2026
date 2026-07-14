"""Vector store — persistence and cosine search over PostgreSQL + pgvector.

Mirrors the repository pattern of the Session 6 layer (``foundation/persistence/
repositories``): the store receives an ``AsyncSession``, owns its own transaction
and never leaks ORM types — callers see plain dataclasses.

Distance metric is cosine (``<=>``): the OpenAI embeddings are normalized, so
cosine and inner product rank identically, and cosine aligns with the
``vector_cosine_ops`` operator class the live session uses when it adds the HNSW
index. There is no vector index yet, so ``search`` runs a sequential scan.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.models import ChunkRow, DocumentRow
from app.generation.rag.schemas import EmbeddedChunk


class DocumentAlreadyExists(Exception):
    """Raised when a document with the same ``source_path`` is already stored."""

    def __init__(self, document_id: int) -> None:
        self.document_id = document_id
        super().__init__(f"Document already ingested (id={document_id})")


@dataclass(frozen=True)
class SearchHit:
    """A single ranked chunk. Repositories never leak SQLAlchemy types."""

    chunk_id: int
    document_id: int
    chunk_type: str
    content: str
    distance: float
    metadata: dict


class VectorStore:
    """Persist documents + chunks and resolve semantic search by cosine distance."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def source_exists(self, source_path: str) -> int | None:
        """Return the id of an existing document with this ``source_path``, if any."""
        result = await self._session.execute(
            select(DocumentRow.id).where(DocumentRow.source_path == source_path)
        )
        return result.scalar_one_or_none()

    async def ingest_document(
        self,
        *,
        source_path: str,
        document_type: str,
        doc_metadata: dict,
        chunks: list[EmbeddedChunk],
        chunk_type: str = "budget_component",
    ) -> tuple[int, int]:
        """Persist one document and all its chunks in a single transaction.

        Raises :class:`DocumentAlreadyExists` if ``source_path`` is already stored.
        Returns ``(document_id, chunks_created)``.
        """
        existing_id = await self.source_exists(source_path)
        if existing_id is not None:
            raise DocumentAlreadyExists(existing_id)

        document = DocumentRow(
            source_path=source_path,
            document_type=document_type,
            meta=doc_metadata,
        )
        self._session.add(document)
        # Flush to get the generated document id before inserting the chunks.
        await self._session.flush()

        self._session.add_all(
            [
                ChunkRow(
                    document_id=document.id,
                    chunk_type=chunk_type,
                    content=chunk.text,
                    embedding=chunk.embedding,
                    meta=chunk.metadata,
                )
                for chunk in chunks
            ]
        )
        await self._session.commit()
        return document.id, len(chunks)

    async def search(self, *, query_vector: list[float], k: int) -> list[SearchHit]:
        """Return the ``k`` chunks closest to ``query_vector`` by cosine distance."""
        distance = ChunkRow.embedding.cosine_distance(query_vector).label("distance")
        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                ChunkRow.meta,
                distance,
            )
            .order_by(distance)
            .limit(k)
        )
        result = await self._session.execute(stmt)
        return [
            SearchHit(
                chunk_id=row.id,
                document_id=row.document_id,
                chunk_type=row.chunk_type,
                content=row.content,
                distance=float(row.distance),
                metadata=row.meta,
            )
            for row in result
        ]
