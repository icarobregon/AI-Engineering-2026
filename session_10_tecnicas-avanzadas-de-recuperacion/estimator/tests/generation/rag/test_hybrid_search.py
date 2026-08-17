"""Unit tests for the lexical branch and hybrid fusion (Session 10).

The store is faked exactly as in ``test_retriever.py`` — no Postgres. These tests
cover the wiring and the contract; that the SQL itself behaves (generated column,
stemming, ``@@`` against the GIN index) is verified against a real PostgreSQL,
because a fake cannot tell us anything about ``to_tsvector``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

import app.dependencies as deps
from app.generation.rag.errors import RetrievalError
from app.generation.rag.retrieval.fulltext_search import search_lexical_chunks
from app.generation.rag.retrieval.hybrid_search import hybrid_search
from app.generation.rag.store.repository import _or_tsquery


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _factory():
    return FakeSession()


def _row(chunk_id: int, *, rank: float = 0.1, distance: float | None = None) -> SimpleNamespace:
    row = SimpleNamespace(
        id=chunk_id,
        document_id=chunk_id * 10,
        chunk_type="budget_component",
        content=f"Chunk {chunk_id}",
        metadata_={"client_sector": "ecommerce", "year": 2024, "budget_id": "BUD-2024-005"},
        lexical_rank=rank,
    )
    if distance is not None:
        row.distance = distance
    return row


class FakeStore:
    """Serves both branches so hybrid can be exercised end to end."""

    def __init__(self, *, vector_rows=(), lexical_rows=(), candidates=0):
        self._vector_rows = list(vector_rows)
        self._lexical_rows = list(lexical_rows)
        self._candidates = candidates
        self.vector_calls: list[dict] = []
        self.lexical_calls: list[dict] = []

    async def search_filtered(self, session, **kwargs):
        self.vector_calls.append(kwargs)
        return self._vector_rows, self._candidates

    async def search_lexical(self, session, **kwargs):
        self.lexical_calls.append(kwargs)
        return self._lexical_rows


@pytest.fixture
def wire(monkeypatch):
    def _wire(store):
        monkeypatch.setattr(deps, "get_async_session_factory", lambda: _factory)
        monkeypatch.setattr(deps, "get_chunk_store", lambda: store)

    return _wire


# --------------------------------------------------------------------------- #
# Lexical branch
# --------------------------------------------------------------------------- #


async def test_lexical_branch_returns_store_ranking_and_forwards_filters(wire):
    store = FakeStore(lexical_rows=[_row(1, rank=0.9), _row(2, rank=0.4)])
    wire(store)

    rows = await search_lexical_chunks("Stripe subscriptions", top_k=50, sectors=["ecommerce"])

    assert [row.id for row in rows] == [1, 2]
    assert store.lexical_calls[0]["query_text"] == "Stripe subscriptions"
    assert store.lexical_calls[0]["top_k"] == 50
    assert store.lexical_calls[0]["sectors"] == ["ecommerce"]


async def test_lexical_branch_returns_empty_without_raising(wire):
    """No literal overlap is a normal outcome, not an error."""
    wire(FakeStore(lexical_rows=[]))
    assert await search_lexical_chunks("purely conceptual paraphrase") == []


async def test_lexical_branch_wraps_store_failure_in_retrieval_error(wire):
    class ExplodingStore(FakeStore):
        async def search_lexical(self, session, **kwargs):
            raise RuntimeError("connection refused")

    wire(ExplodingStore())

    with pytest.raises(RetrievalError):
        await search_lexical_chunks("anything")


def test_lexical_query_uses_or_semantics_not_and():
    """Regression guard for the trap that silently disables the lexical branch.

    ``websearch_to_tsquery`` and ``plainto_tsquery`` both combine terms with AND.
    Under AND semantics a long project description — the system's actual input —
    matches nothing, the branch returns [] for every real query, hybrid degrades to
    vector-only WITHOUT ERROR, and the A/B/C/D table concludes that hybrid search
    adds nothing.

    Asserted on the compiled SQL because no fake store can catch this and the
    behaviour is PostgreSQL's, not ours.
    """
    compiled = _or_tsquery("E-commerce platform with product catalog and admin panel").compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)

    assert "plainto_tsquery" in sql
    assert "AS TSQUERY" in sql
    # The AND -> OR swap must actually reach the database...
    assert "&" in compiled.params.values()
    assert "|" in compiled.params.values()
    # ...and the AND-combining builder must not be what runs.
    assert "websearch_to_tsquery" not in sql


# --------------------------------------------------------------------------- #
# Hybrid fusion
# --------------------------------------------------------------------------- #


async def test_hybrid_fuses_both_branches_and_rewards_consensus(wire):
    """Chunk 2 is 2nd semantically and 5th lexically; chunk 1 is 1st and absent.

    Consensus must take the top slot — the failure mode this session attacks.
    """
    store = FakeStore(
        vector_rows=[_row(1, distance=0.30), _row(2, distance=0.35), _row(3, distance=0.40)],
        lexical_rows=[_row(90), _row(91), _row(92), _row(93), _row(2)],
        candidates=29,
    )
    wire(store)

    result = await hybrid_search([0.0] * 1536, "Stripe subscriptions", top_k=5)

    assert next(chunk.id for chunk in result.chunks) == 2
    assert result.low_confidence is False
    assert result.candidates_evaluated == 29


async def test_hybrid_keeps_the_real_distance_and_never_invents_one(wire):
    """A chunk in both branches keeps its cosine distance; lexical-only gets None.

    A sentinel here would be rendered into the generator's prompt as a fact.
    """
    store = FakeStore(
        vector_rows=[_row(1, distance=0.31)],
        lexical_rows=[_row(1), _row(77)],
    )
    wire(store)

    result = await hybrid_search([0.0] * 1536, "Stripe", top_k=5)
    by_id = {chunk.id: chunk for chunk in result.chunks}

    assert by_id[1].distance == pytest.approx(0.31)  # found by both
    assert by_id[77].distance is None  # lexical only


async def test_hybrid_deduplicates_chunks_found_by_both_branches(wire):
    store = FakeStore(vector_rows=[_row(1, distance=0.3)], lexical_rows=[_row(1)])
    wire(store)

    result = await hybrid_search([0.0] * 1536, "q", top_k=5)

    assert [chunk.id for chunk in result.chunks] == [1]


async def test_hybrid_truncates_to_top_k_after_fusion(wire):
    """Fusion happens over the wide recall set; the cut happens after."""
    store = FakeStore(
        vector_rows=[_row(i, distance=0.1 * i) for i in range(1, 11)],
        lexical_rows=[_row(i) for i in range(20, 30)],
    )
    wire(store)

    result = await hybrid_search([0.0] * 1536, "q", top_k=5, recall_k=50)

    assert len(result.chunks) == 5
    assert store.vector_calls[0]["top_k"] == 50  # branches recall wide...
    assert store.lexical_calls[0]["top_k"] == 50  # ...both of them


async def test_hybrid_survives_a_dead_lexical_branch(wire):
    """Degrades to the vector ranking, which is the pre-Session-10 behaviour."""
    store = FakeStore(
        vector_rows=[_row(1, distance=0.2), _row(2, distance=0.3)],
        lexical_rows=[],
    )
    wire(store)

    result = await hybrid_search([0.0] * 1536, "q", top_k=5)

    assert [chunk.id for chunk in result.chunks] == [1, 2]
    assert result.low_confidence is False


async def test_hybrid_low_confidence_only_when_both_branches_are_empty(wire):
    wire(FakeStore(vector_rows=[], lexical_rows=[], candidates=29))

    result = await hybrid_search([0.0] * 1536, "q", top_k=5)

    assert result.chunks == []
    assert result.low_confidence is True


async def test_hybrid_applies_the_same_structural_filters_to_both_branches(wire):
    """If the branches filtered differently, fusion would mix two populations."""
    store = FakeStore(vector_rows=[_row(1, distance=0.2)], lexical_rows=[_row(1)])
    wire(store)

    await hybrid_search(
        [0.0] * 1536,
        "q",
        sectors=["finance"],
        project_year_min=2022,
        project_year_max=2024,
        chunk_types=["budget_component"],
    )

    for axis in ("sectors", "project_year_min", "project_year_max", "chunk_types"):
        assert store.vector_calls[0][axis] == store.lexical_calls[0][axis]
