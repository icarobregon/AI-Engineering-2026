"""Integration tests for the Retrieval stage against real Postgres + pgvector.

Excluded from the default run (``addopts = -m 'not integration'``). To run:

    docker compose up -d
    uv run python scripts/query_examples.py   # seeds the corpus if empty
    uv run pytest -m integration -v

These exist because the interesting part of retrieval is SQL, and SQL doubled
with a fake proves nothing: JSONB filters, the ``distance < threshold``
predicate and the operator/operator-class alignment of the HNSW index either
work in Postgres or they do not.

No OpenAI either: query vectors are taken from chunks already in the corpus, so
a chunk is always at distance 0 from itself and the assertions are exact rather
than approximate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.foundation.persistence.database import _async_database_url
from app.generation.rag.schemas import RetrievalFilters
from app.generation.rag.store.models import ChunkRow
from app.generation.rag.store.repository import ChunkStore

pytestmark = pytest.mark.integration


@pytest.fixture
async def session():
    """A session on an engine private to this test.

    Not ``get_async_session_factory()``: that engine is an ``lru_cache``
    singleton, and pytest-asyncio gives each test its own event loop. Reusing
    pooled asyncpg connections across loops fails with "Event loop is closed"
    on the second test.
    """
    engine = create_async_engine(_async_database_url())
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
async def corpus_guard(session):
    """Skip the whole module if the corpus is not seeded."""
    count = (await session.execute(select(func.count(ChunkRow.id)))).scalar_one()
    if count == 0:
        pytest.skip("empty corpus — run scripts/query_examples.py first")
    return count


@pytest.fixture
async def probe(session, corpus_guard):
    """A real chunk plus its own embedding, used as the query vector."""
    row = (
        await session.execute(
            select(ChunkRow.id, ChunkRow.embedding, ChunkRow.metadata_)
            .where(ChunkRow.metadata_["client_sector"].astext == "ecommerce")
            .order_by(ChunkRow.id)
            .limit(1)
        )
    ).first()
    return row


async def test_self_query_returns_itself_at_distance_zero(session, probe):
    store = ChunkStore()
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=1,
        distance_threshold=2.0,
        filters=RetrievalFilters(),
    )
    assert rows[0].id == probe.id
    assert rows[0].distance == pytest.approx(0.0, abs=1e-6)


async def test_threshold_excludes_everything_when_impossibly_strict(session, probe):
    store = ChunkStore()
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=10,
        distance_threshold=0.0,  # strict inequality: not even the chunk itself
        filters=RetrievalFilters(),
    )
    assert rows == []


async def test_sector_filter_only_returns_that_sector(session, probe):
    store = ChunkStore()
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=30,
        distance_threshold=2.0,
        filters=RetrievalFilters(sectors=["finance"]),
    )
    assert rows, "the corpus has finance chunks"
    assert {r.metadata_["client_sector"] for r in rows} == {"finance"}


async def test_country_filter_reads_the_metadata_added_in_session_9(session, probe):
    store = ChunkStore()
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=30,
        distance_threshold=2.0,
        filters=RetrievalFilters(countries=["DE"]),
    )
    assert rows, "country must be persisted in chunk metadata"
    assert {r.metadata_["country"] for r in rows} == {"DE"}


async def test_year_range_filter_casts_jsonb_to_int(session, probe):
    store = ChunkStore()
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=30,
        distance_threshold=2.0,
        filters=RetrievalFilters(project_year_min=2024),
    )
    assert rows
    # Lexicographic comparison would let "2023" through; the cast must not.
    assert all(r.metadata_["year"] >= 2024 for r in rows)


async def test_count_candidates_matches_the_filtered_rows(session, probe):
    store = ChunkStore()
    filters = RetrievalFilters(sectors=["ecommerce"])
    counted = await store.count_candidates(session, filters=filters)
    rows = await store.search_filtered(
        session,
        query_vector=list(probe.embedding),
        top_k=1000,
        distance_threshold=2.0,
        filters=filters,
    )
    assert counted == len(rows)


async def test_post_filtering_returns_a_subset_of_the_wide_pool(session, probe):
    store = ChunkStore()
    filters = RetrievalFilters(sectors=["ecommerce"])
    rows = await store.search_wide_then_filter(
        session,
        query_vector=list(probe.embedding),
        top_k=5,
        distance_threshold=2.0,
        filters=filters,
        wide_k=15,
    )
    assert rows
    assert {r.metadata_["client_sector"] for r in rows} == {"ecommerce"}
    # Ordering by distance must survive the outer query.
    assert [r.distance for r in rows] == sorted(r.distance for r in rows)


async def test_hnsw_index_is_aligned_with_the_cosine_operator(session, probe):
    """The silent antipattern: an index the planner cannot use raises nothing.

    ``enable_seqscan = off`` forces the planner's hand — at 60 chunks a
    sequential scan is genuinely cheaper, so this asserts *usability* of the
    index, not that it is chosen today.
    """
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (
        await session.execute(
            text(
                "EXPLAIN SELECT id FROM chunks "
                "ORDER BY (embedding::halfvec(1536)) <=> "
                "(SELECT embedding::halfvec(1536) FROM chunks ORDER BY id LIMIT 1) LIMIT 5"
            )
        )
    ).scalars().all()
    assert any("chunks_embedding_halfvec_idx" in line for line in plan), "\n".join(plan)
