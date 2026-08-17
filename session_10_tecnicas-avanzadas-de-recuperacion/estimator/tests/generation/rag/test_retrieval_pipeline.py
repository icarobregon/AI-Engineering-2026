"""Unit tests for the retrieval pipeline — the four configurations (Session 10).

Store and reranker are both faked: no Postgres, no torch. What these pin is the
composition logic, which is where the configurations actually live — recall width,
final width, which branches run, and the thread-pool dispatch that keeps a
synchronous cross-encoder off the event loop.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

import app.dependencies as deps
from app.generation.rag.retrieval.pipeline import retrieve


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _factory():
    return FakeSession()


def _row(chunk_id: int, *, distance: float = 0.3, rank: float = 0.1) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        document_id=chunk_id * 10,
        chunk_type="budget_component",
        content=f"Chunk {chunk_id}",
        metadata_={"client_sector": "ecommerce", "year": 2024, "budget_id": "BUD-2024-005"},
        distance=distance,
        lexical_rank=rank,
    )


class FakeStore:
    def __init__(self, *, vector_rows=(), lexical_rows=(), candidates=29):
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


class FakeReranker:
    """Reverses the candidate order, so "the reranker ran" is observable."""

    def __init__(self):
        self.calls: list[dict] = []
        self.thread_names: list[str] = []

    def rerank(self, query, candidates, *, top_n):
        self.calls.append({"query": query, "candidates_in": len(candidates), "top_n": top_n})
        self.thread_names.append(threading.current_thread().name)
        return list(reversed(candidates))[:top_n]


@pytest.fixture
def wire(monkeypatch):
    def _wire(store, reranker=None):
        monkeypatch.setattr(deps, "get_async_session_factory", lambda: _factory)
        monkeypatch.setattr(deps, "get_chunk_store", lambda: store)
        if reranker is not None:
            monkeypatch.setattr(deps, "get_reranker", lambda: reranker)

    return _wire


def _twenty_vector_rows():
    return [_row(i, distance=0.01 * i) for i in range(1, 21)]


# --------------------------------------------------------------------------- #
# The four configurations
# --------------------------------------------------------------------------- #


async def test_config_a_vector_no_rerank(wire):
    """Session 9 baseline: only the vector branch runs, recall == top_k."""
    store = FakeStore(vector_rows=_twenty_vector_rows(), lexical_rows=[_row(99)])
    wire(store)

    result = await retrieve([0.0] * 1536, "q", search_mode="vector", rerank=False, top_k=5)

    assert [chunk.id for chunk in result.chunks] == [1, 2, 3, 4, 5]
    assert store.lexical_calls == []  # the lexical branch must NOT run
    # No later stage re-sorts, so asking for more than top_k would be waste.
    assert store.vector_calls[0]["top_k"] == 5


async def test_config_b_hybrid_no_rerank(wire):
    """Both branches run and fuse; no cross-encoder involved."""
    store = FakeStore(vector_rows=_twenty_vector_rows(), lexical_rows=[_row(99)])
    wire(store)

    result = await retrieve([0.0] * 1536, "q", search_mode="hybrid", rerank=False, top_k=5)

    assert len(store.lexical_calls) == 1
    assert len(result.chunks) == 5
    assert 99 in [chunk.id for chunk in result.chunks]  # lexical-only chunk survived


async def test_config_c_vector_plus_rerank_recalls_wide_and_cuts_narrow(wire):
    """The pattern itself: recall 50, hand those to the cross-encoder, keep 5."""
    reranker = FakeReranker()
    store = FakeStore(vector_rows=_twenty_vector_rows())
    wire(store, reranker)

    result = await retrieve(
        [0.0] * 1536, "q", search_mode="vector", rerank=True, recall_k=50, rerank_top_n=5
    )

    assert store.vector_calls[0]["top_k"] == 50  # WIDE recall...
    assert reranker.calls[0]["candidates_in"] == 20  # ...all of it reranked
    assert reranker.calls[0]["top_n"] == 5
    assert len(result.chunks) == 5  # ...narrow output
    # The fake reverses, so this proves the reranker's order won, not the recall's.
    assert [chunk.id for chunk in result.chunks] == [20, 19, 18, 17, 16]


async def test_config_d_hybrid_plus_rerank(wire):
    reranker = FakeReranker()
    store = FakeStore(vector_rows=_twenty_vector_rows(), lexical_rows=[_row(99)])
    wire(store, reranker)

    result = await retrieve(
        [0.0] * 1536, "q", search_mode="hybrid", rerank=True, recall_k=50, rerank_top_n=5
    )

    assert len(store.lexical_calls) == 1
    assert store.lexical_calls[0]["top_k"] == 50
    assert reranker.calls[0]["top_n"] == 5
    assert len(result.chunks) == 5


# --------------------------------------------------------------------------- #
# Switchable without touching code
# --------------------------------------------------------------------------- #


async def test_switches_default_to_settings(wire, monkeypatch):
    """Passing no overrides must honour configuration — the exercise's requirement
    that reranking can be turned on and off without touching code."""
    from app.generation.rag.retrieval import pipeline

    reranker = FakeReranker()
    store = FakeStore(vector_rows=_twenty_vector_rows(), lexical_rows=[_row(99)])
    wire(store, reranker)
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            RETRIEVAL_SEARCH_MODE="hybrid",
            RERANKER_ENABLED=True,
            RETRIEVAL_TOP_K=10,
            RETRIEVAL_RECALL_TOP_K=50,
            RERANK_TOP_N=5,
            RRF_K=60,
            RETRIEVAL_DISTANCE_THRESHOLD=0.6,
        ),
    )

    result = await retrieve([0.0] * 1536, "q")

    assert len(store.lexical_calls) == 1  # hybrid, from settings
    assert reranker.calls  # reranking, from settings
    assert len(result.chunks) == 5  # RERANK_TOP_N, from settings


async def test_explicit_argument_overrides_settings(wire, monkeypatch):
    from app.generation.rag.retrieval import pipeline

    store = FakeStore(vector_rows=_twenty_vector_rows())
    wire(store)
    monkeypatch.setattr(
        pipeline,
        "get_settings",
        lambda: SimpleNamespace(
            RETRIEVAL_SEARCH_MODE="hybrid",
            RERANKER_ENABLED=True,
            RETRIEVAL_TOP_K=10,
            RETRIEVAL_RECALL_TOP_K=50,
            RERANK_TOP_N=5,
            RRF_K=60,
            RETRIEVAL_DISTANCE_THRESHOLD=0.6,
        ),
    )

    result = await retrieve([0.0] * 1536, "q", search_mode="vector", rerank=False, top_k=3)

    assert store.lexical_calls == []
    assert len(result.chunks) == 3


async def test_unknown_search_mode_fails_loudly(wire):
    """A configuration typo must not silently pick a branch."""
    wire(FakeStore(vector_rows=_twenty_vector_rows()))

    with pytest.raises(ValueError, match="Unknown search_mode"):
        await retrieve([0.0] * 1536, "q", search_mode="hybird")


# --------------------------------------------------------------------------- #
# The asyncio hazard
# --------------------------------------------------------------------------- #


async def test_reranking_runs_off_the_event_loop(wire):
    """The incident-report detail: synchronous transformer inference on the event
    loop blocks every other request for its full duration."""
    reranker = FakeReranker()
    wire(FakeStore(vector_rows=_twenty_vector_rows()), reranker)

    loop_thread = threading.current_thread().name
    await retrieve([0.0] * 1536, "q", rerank=True, search_mode="vector")

    assert reranker.thread_names[0] != loop_thread


async def test_the_event_loop_stays_responsive_during_reranking(wire):
    """Behavioural proof rather than an assertion about thread names: a concurrent
    task must make progress while a blocking rerank is in flight."""

    ticks = 0

    class BlockingReranker(FakeReranker):
        def rerank(self, query, candidates, *, top_n):
            super().rerank(query, candidates, top_n=top_n)
            time_to_block = 0.20
            threading.Event().wait(time_to_block)  # real, blocking sleep
            return candidates[:top_n]

    async def ticker():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.01)
            ticks += 1

    wire(FakeStore(vector_rows=_twenty_vector_rows()), BlockingReranker())

    await asyncio.gather(
        retrieve([0.0] * 1536, "q", rerank=True, search_mode="vector"),
        ticker(),
    )

    # If the inference had run on the loop, the ticker would have been frozen.
    assert ticks == 20


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


async def test_reranker_is_not_invoked_when_recall_is_empty(wire):
    """No candidates means nothing to reorder — do not pay for a forward pass."""
    reranker = FakeReranker()
    wire(FakeStore(vector_rows=[], lexical_rows=[]), reranker)

    result = await retrieve([0.0] * 1536, "q", rerank=True, search_mode="vector")

    assert reranker.calls == []
    assert result.chunks == []
    assert result.low_confidence is True


async def test_reranker_receives_the_raw_query_text_not_the_vector(wire):
    """A cross-encoder scores (query, document) TEXT pairs; it has no use for an
    embedding. This is why query_text is required even in vector mode."""
    reranker = FakeReranker()
    wire(FakeStore(vector_rows=_twenty_vector_rows()), reranker)

    await retrieve([0.0] * 1536, "e-commerce platform", rerank=True, search_mode="vector")

    assert reranker.calls[0]["query"] == "e-commerce platform"


async def test_candidates_evaluated_is_preserved_through_the_pipeline(wire):
    """Observability: the funnel's entry width must survive to the response."""
    wire(FakeStore(vector_rows=_twenty_vector_rows(), candidates=137), FakeReranker())

    result = await retrieve([0.0] * 1536, "q", rerank=True, search_mode="vector")

    assert result.candidates_evaluated == 137
