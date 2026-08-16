"""Async data-access layer for the vector store.

The store never opens or commits sessions: the caller (ingest service,
retriever) owns the ``AsyncSession`` so a whole ingest — duplicate check,
document row, chunk rows — fits in ONE transaction. A failure anywhere rolls
everything back and leaves no orphan ``documents`` row.
"""

from __future__ import annotations

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Integer, Row, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.schemas import EmbeddedChunk, RetrievalFilters
from app.generation.rag.store.models import ChunkRow, DocumentRow, EMBEDDING_DIMENSIONS

# The structural chunker emits one chunk per budget component; the vocabulary
# is queryable thanks to the index on ``chunk_type`` (live-session filters).
BUDGET_COMPONENT = "budget_component"


class ChunkStore:
    """CRUD + similarity search over ``documents``/``chunks``."""

    async def find_document_id(self, session: AsyncSession, source_path: str) -> int | None:
        """Return the id of the document already ingested from ``source_path``,
        or ``None``. Backs the application-level 409 duplicate guard."""
        stmt = select(DocumentRow.id).where(DocumentRow.source_path == source_path)
        return (await session.execute(stmt)).scalar_one_or_none()

    async def persist_document_with_chunks(
        self,
        session: AsyncSession,
        *,
        source_path: str,
        document_type: str,
        doc_metadata: dict,
        embedded_chunks: list[EmbeddedChunk],
    ) -> int:
        """Insert the document row plus all its chunk rows. No commit here —
        the caller's transaction decides when (and whether) anything lands."""
        document = DocumentRow(
            source_path=source_path,
            document_type=document_type,
            metadata_=doc_metadata,
        )
        session.add(document)
        await session.flush()  # assigns document.id without committing

        session.add_all(
            ChunkRow(
                document_id=document.id,
                chunk_type=BUDGET_COMPONENT,
                content=chunk.text,
                embedding=chunk.embedding,
                metadata_=chunk.metadata,
            )
            for chunk in embedded_chunks
        )
        return document.id

    async def search(
        self, session: AsyncSession, *, query_vector: list[float], k: int
    ) -> list[Row]:
        """k nearest chunks by cosine distance (``<=>``), sequential scan.

        Cosine over L2/inner product: OpenAI embeddings are normalized so the
        ranking would be equivalent, but cosine keeps us aligned with the RAG
        literature AND with the ``vector_cosine_ops`` operator class of the
        HNSW index the live session adds — operator/index mismatch makes
        Postgres silently ignore the index.
        """
        # distance = ChunkRow.embedding.cosine_distance(query_vector)
        distance = cast(ChunkRow.embedding, HALFVEC(EMBEDDING_DIMENSIONS)).cosine_distance(query_vector)
        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                # Explicit label: subqueries key their columns by this name,
                # and ``RetrievedChunk.from_row`` reads ``row.metadata_`` for
                # both the pre- and post-filtering shapes.
                ChunkRow.metadata_.label("metadata_"),
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(k)
        )
        return list((await session.execute(stmt)).all())

    # --- Session 9: retrieval with quality threshold + structural filters ----

    @staticmethod
    def _distance(query_vector: list[float]):
        """Cosine distance expression, cast to halfvec.

        The cast is not decoration: ``chunks_embedding_halfvec_idx`` (migration
        0003) is an *expression* index over ``embedding::halfvec(1536)``, so
        only a query ordering by this very expression can use it. Ranking by
        the bare column silently falls back to a sequential scan.
        """
        return cast(ChunkRow.embedding, HALFVEC(EMBEDDING_DIMENSIONS)).cosine_distance(
            query_vector
        )

    @staticmethod
    def _structural_conditions(filters: RetrievalFilters) -> list:
        """Translate optional filters into SQL predicates over the JSONB blob.

        Built conditionally instead of with the ``(:filter IS NULL OR ...)``
        idiom of the session material. That idiom exists to keep ONE statement
        shape when writing raw SQL with a fixed parameter list; with a query
        builder it buys nothing and costs something, because the planner has to
        carry OR branches that are constant-false for this execution.

        Everything filters on ``chunks.metadata`` (GIN-indexed) rather than on
        ``documents``: sector, country, year and technology all travel with the
        chunk, so no join is needed on the hot path.
        """
        conditions = []
        if filters.sectors:
            conditions.append(ChunkRow.metadata_["client_sector"].astext.in_(filters.sectors))
        if filters.countries:
            conditions.append(ChunkRow.metadata_["country"].astext.in_(filters.countries))
        if filters.technologies:
            conditions.append(
                ChunkRow.metadata_["main_technology"].astext.in_(filters.technologies)
            )
        if filters.chunk_types:
            conditions.append(ChunkRow.chunk_type.in_(filters.chunk_types))
        year = cast(ChunkRow.metadata_["year"].astext, Integer)
        if filters.project_year_min is not None:
            conditions.append(year >= filters.project_year_min)
        if filters.project_year_max is not None:
            conditions.append(year <= filters.project_year_max)
        return conditions

    async def count_candidates(
        self, session: AsyncSession, *, filters: RetrievalFilters
    ) -> int:
        """How many chunks survive the structural filters, before similarity.

        Feeds ``total_candidates_considered``, which is what makes a
        ``low_confidence`` answer diagnosable: "nothing passed the threshold"
        means something very different out of 4 candidates than out of 60.
        """
        stmt = select(func.count(ChunkRow.id)).where(*self._structural_conditions(filters))
        return int((await session.execute(stmt)).scalar_one())

    async def search_filtered(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        top_k: int,
        distance_threshold: float,
        filters: RetrievalFilters,
    ) -> list[Row]:
        """Pre-filtering search: structural predicates + threshold + top-K.

        Pre-filtering (filter, then rank what is left) is correct while the
        filters are selective enough to leave a pool much larger than ``top_k``.
        When they are not, ``search_wide_then_filter`` is the alternative.
        """
        distance = self._distance(query_vector)
        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                # Explicit label: subqueries key their columns by this name,
                # and ``RetrievedChunk.from_row`` reads ``row.metadata_`` for
                # both the pre- and post-filtering shapes.
                ChunkRow.metadata_.label("metadata_"),
                distance.label("distance"),
            )
            .where(*self._structural_conditions(filters), distance < distance_threshold)
            .order_by(distance)
            .limit(top_k)
        )
        return list((await session.execute(stmt)).all())

    async def search_wide_then_filter(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        top_k: int,
        distance_threshold: float,
        filters: RetrievalFilters,
        wide_k: int,
    ) -> list[Row]:
        """Post-filtering variant: rank a wide pool first, then filter it.

        Worth it when the filter has LOW selectivity (it keeps most of the
        corpus): the vector index does the expensive work over an unfiltered
        set — which is exactly what an HNSW graph is good at — and the cheap
        predicate runs over ``wide_k`` rows instead of the whole table.

        The trade-off is real and asymmetric: if the filter is selective, the
        wide pool may contain no matching row at all and this returns fewer
        results than ``search_filtered`` would. Callers pick per query, they do
        not get a default that is right in both regimes.
        """
        distance = self._distance(query_vector)
        candidates = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                # Explicit label: subqueries key their columns by this name,
                # and ``RetrievedChunk.from_row`` reads ``row.metadata_`` for
                # both the pre- and post-filtering shapes.
                ChunkRow.metadata_.label("metadata_"),
                distance.label("distance"),
            )
            .where(distance < distance_threshold)
            .order_by(distance)
            .limit(wide_k)
            .subquery()
        )
        conditions = []
        if filters.sectors:
            conditions.append(candidates.c.metadata_["client_sector"].astext.in_(filters.sectors))
        if filters.countries:
            conditions.append(candidates.c.metadata_["country"].astext.in_(filters.countries))
        if filters.technologies:
            conditions.append(
                candidates.c.metadata_["main_technology"].astext.in_(filters.technologies)
            )
        if filters.chunk_types:
            conditions.append(candidates.c.chunk_type.in_(filters.chunk_types))
        year = cast(candidates.c.metadata_["year"].astext, Integer)
        if filters.project_year_min is not None:
            conditions.append(year >= filters.project_year_min)
        if filters.project_year_max is not None:
            conditions.append(year <= filters.project_year_max)

        stmt = (
            select(candidates)
            .where(*conditions)
            .order_by(candidates.c.distance)
            .limit(top_k)
        )
        return list((await session.execute(stmt)).all())
