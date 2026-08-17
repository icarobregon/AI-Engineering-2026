"""Async data-access layer for the vector store.

The store never opens or commits sessions: the caller (ingest service,
retriever) owns the ``AsyncSession`` so a whole ingest — duplicate check,
document row, chunk rows — fits in ONE transaction. A failure anywhere rolls
everything back and leaves no orphan ``documents`` row.
"""

from __future__ import annotations

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import Integer, Row, Text, cast, func, select
from sqlalchemy.dialects.postgresql import TSQUERY
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.rag.schemas import EmbeddedChunk
from app.generation.rag.store.models import (
    ChunkRow,
    DocumentRow,
    EMBEDDING_DIMENSIONS,
    TEXT_SEARCH_CONFIG,
)

# The structural chunker emits one chunk per budget component; the vocabulary
# is queryable thanks to the index on ``chunk_type`` (live-session filters).
BUDGET_COMPONENT = "budget_component"


def _or_tsquery(query_text: str):
    """Build an OR-combined ``tsquery`` from free-form text.

    **Why not ``websearch_to_tsquery`` or ``plainto_tsquery`` directly:** both
    combine terms with AND. For a search box that is the right default, but the
    input here is a project description — often a whole meeting transcript. AND-ing
    a dozen stemmed terms matches nothing in a company-sized corpus, so the lexical
    branch would return an empty list for essentially every real query, hybrid
    search would silently degrade to vector-only, and the A/B/C/D measurement would
    "prove" that hybrid adds nothing when in fact this branch never ran. Verified:
    ``websearch_to_tsquery('english', 'E-commerce platform with product catalog,
    shopping cart checkout and an admin panel')`` yields
    ``'e-commerc' <-> 'e' <-> 'commerc' & 'platform' & 'product' & ...`` — nine
    mandatory terms, zero matches.

    With OR, a document matches on any term and ``ts_rank`` does the discriminating:
    it scores documents higher when they match MORE of the query's terms. Note what it
    does NOT do: there is no IDF weighting, so a rare term counts exactly as much as an
    omnipresent one (measured on this corpus: ``ts_rank`` is byte-identical for a term
    matching 19 of 60 chunks and one matching 0). Nor is there length normalisation by
    default, so a long chunk accumulates matches and outranks a short precise one.

    **Implementation:** ``plainto_tsquery`` does the tokenizing, stop-wording and
    stemming — with the same configuration as the indexed column — and never raises
    on malformed input (it returns an empty tsquery and logs a notice). Its output
    joins terms with ``&``, so swapping the operator on the rendered text turns the
    conjunction into a disjunction.

    The swap is safe for this corpus, with one honest caveat. Almost everything lexes
    without an ``&`` (verified: ``R&D`` becomes ``'r' & 'd'``), but PostgreSQL's ``url``
    and ``url_path`` token types keep ``&`` verbatim, so an input containing a query
    string can have the operator rewritten INSIDE such a lexeme. The consequence is
    bounded — the ``host`` lexeme of the same URL survives and still matches, so it
    perturbs the rank rather than losing the result, and no input tried produced
    invalid tsquery syntax. Zero of the 60 chunks in this corpus contain a URL. The
    robust form, if this ever indexes URLs, is to build the disjunction from
    ``tsvector_to_array(to_tsvector(...))`` with ``quote_literal`` — which also
    deduplicates, something ``plainto_tsquery`` does not.

    An input that reduces to nothing (only stop words, only punctuation) produces an
    empty tsquery, which matches no rows — the correct outcome, not an error.
    """
    return cast(
        func.replace(cast(func.plainto_tsquery(TEXT_SEARCH_CONFIG, query_text), Text), "&", "|"),
        TSQUERY,
    )


def _structural_filters(
    *,
    sectors: list[str] | None,
    project_year_min: int | None,
    project_year_max: int | None,
    chunk_types: list[str] | None,
) -> list:
    """Build the metadata/column predicates shared by every search branch.

    Extracted so the vector and lexical branches cannot drift apart: if the two
    applied even slightly different filters, hybrid search would be fusing two
    rankings drawn from different populations, and the fused result would be
    wrong in a way no test of either branch alone would catch.

    Each axis follows the "``None`` means do not filter" convention; ``sectors``
    and ``year`` live in JSONB (``client_sector``/``year``), ``chunk_type`` is a
    typed column.
    """
    sector_col = ChunkRow.metadata_["client_sector"].astext
    year_col = cast(ChunkRow.metadata_["year"].astext, Integer)

    filters = []
    if sectors:
        filters.append(sector_col.in_(sectors))
    if project_year_min is not None:
        filters.append(year_col >= project_year_min)
    if project_year_max is not None:
        filters.append(year_col <= project_year_max)
    if chunk_types:
        filters.append(ChunkRow.chunk_type.in_(chunk_types))
    return filters


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
        chunk_type: str = BUDGET_COMPONENT,
    ) -> int:
        """Insert the document row plus all its chunk rows. No commit here —
        the caller's transaction decides when (and whether) anything lands.

        ``chunk_type`` is stamped on every chunk (filterable column); it
        defaults to ``budget_component`` so existing callers are unaffected."""
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
                chunk_type=chunk_type,
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
        distance = cast(ChunkRow.embedding, HALFVEC(EMBEDDING_DIMENSIONS)).cosine_distance(
            query_vector
        )
        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                ChunkRow.metadata_,
                distance.label("distance"),
            )
            .order_by(distance)
            .limit(k)
        )
        return list((await session.execute(stmt)).all())

    async def search_filtered(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        top_k: int = 10,
        distance_threshold: float = 0.6,
        sectors: list[str] | None = None,
        project_year_min: int | None = None,
        project_year_max: int | None = None,
        chunk_types: list[str] | None = None,
    ) -> tuple[list[Row], int]:
        """k-NN search with structural pre-filtering and a relevance threshold.

        Session 9 retrieval. Structural filters (sector / project year / chunk
        type) narrow the candidate space BEFORE the vector ranking — the metadata
        is persisted in JSONB (``client_sector``, ``year``) and the ``chunk_type``
        column. Each filter follows the ``(:filter IS NULL OR …)`` pattern: a
        ``None`` filter simply does not apply. The distance threshold then drops
        chunks that are not actually close (no "confidently retrieving garbage").

        Returns
        -------
        tuple[list[Row], int]
            ``(rows, candidates_evaluated)`` where ``rows`` are the top-k chunks
            under the threshold (ascending distance) and ``candidates_evaluated``
            is how many chunks matched the structural filters before the
            threshold/limit were applied.
        """
        structural_filters = _structural_filters(
            sectors=sectors,
            project_year_min=project_year_min,
            project_year_max=project_year_max,
            chunk_types=chunk_types,
        )

        distance = cast(ChunkRow.embedding, HALFVEC(EMBEDDING_DIMENSIONS)).cosine_distance(
            query_vector
        )

        count_stmt = select(func.count()).select_from(ChunkRow).where(*structural_filters)
        candidates_evaluated = int((await session.execute(count_stmt)).scalar_one())

        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                ChunkRow.metadata_,
                distance.label("distance"),
            )
            .where(*structural_filters)
            .where(distance <= distance_threshold)
            .order_by(distance)
            .limit(top_k)
        )
        rows = list((await session.execute(stmt)).all())
        return rows, candidates_evaluated

    async def search_lexical(
        self,
        session: AsyncSession,
        *,
        query_text: str,
        top_k: int = 50,
        sectors: list[str] | None = None,
        project_year_min: int | None = None,
        project_year_max: int | None = None,
        chunk_types: list[str] | None = None,
    ) -> list[Row]:
        """Keyword search over the generated ``content_tsv`` column (Session 10).

        The lexical half of hybrid search: the branch that still finds a budget
        when the query names something literally — "Stripe", "SAP", "ISO 27001",
        "React Native". Those are exactly the terms with the least general
        semantic mass and the most discriminative value, i.e. the ones that
        survive embedding compression worst.

        The query is built by :func:`_or_tsquery`, which combines terms with OR
        rather than AND. That is not a detail: with AND semantics a long project
        description matches nothing at all, and the branch would look like it was
        working while contributing nothing to the fusion.

        The text search configuration comes from
        :data:`~app.generation.rag.store.models.TEXT_SEARCH_CONFIG`, the same
        constant the generated column was built with. Querying with a different
        configuration than the one that built the tsvector silently under-matches,
        so the two are never allowed to be independent literals.

        Ranking is ``ts_rank``. Two honesties: it is **not BM25** (it does not
        normalise by document length as carefully), and its scale is not
        comparable to cosine distance — which is precisely why fusion happens by
        RANK and not by score. Its absolute value is therefore only ever used to
        order this branch's own results.

        Parameters
        ----------
        query_text:
            Raw query text. An input that reduces to an empty tsquery (only stop
            words, or only punctuation) matches nothing and yields ``[]``.
        top_k:
            Recall width for this branch. Defaults to 50: the recall stage is
            asked for coverage, not for a fine ordering.
        sectors, project_year_min, project_year_max, chunk_types:
            The SAME structural filters as :meth:`search_filtered`, applied
            through the shared helper so both branches see one population.

        Returns
        -------
        list[Row]
            Rows ordered by descending ``lexical_rank``, carrying the same
            columns as the vector branch plus ``lexical_rank``. Ties break by
            ascending ``id`` so the ranking — and therefore the fusion built on
            top of it — is deterministic.
        """
        tsquery = _or_tsquery(query_text)
        lexical_rank = func.ts_rank(ChunkRow.content_tsv, tsquery)

        stmt = (
            select(
                ChunkRow.id,
                ChunkRow.document_id,
                ChunkRow.chunk_type,
                ChunkRow.content,
                ChunkRow.metadata_,
                lexical_rank.label("lexical_rank"),
            )
            .where(
                *_structural_filters(
                    sectors=sectors,
                    project_year_min=project_year_min,
                    project_year_max=project_year_max,
                    chunk_types=chunk_types,
                )
            )
            # @@ is the match operator; this is what the GIN index serves.
            .where(ChunkRow.content_tsv.op("@@")(tsquery))
            .order_by(lexical_rank.desc(), ChunkRow.id)
            .limit(top_k)
        )
        return list((await session.execute(stmt)).all())
