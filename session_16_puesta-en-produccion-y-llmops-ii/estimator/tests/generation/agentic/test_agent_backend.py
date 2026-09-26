"""The composition-root adapter behind search_budgets (Session 12).

This is the piece that does the real work — it wires the tool to the S9-S11
retrieval pipeline and rolls the retrieved TASKS up into the historical MODULES
the agent actually reasons about — and it was the one piece with no test at all.
Everything here is stubbed: no network, no database.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import app.dependencies as deps


@dataclass
class _Chunk:
    id: int
    content: str = "Module: Fleet & Routing\nComponent: route planning"
    sector: str = "logistics"
    distance: float = 0.4
    estimated_hours: int | None = 20


@dataclass
class _Result:
    chunks: list


class _Session:
    """Async-context session whose execute() replays canned result rows."""

    def __init__(self, rows: list[list]):
        self._rows = rows
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _stmt):
        rows = self._rows[min(self.calls, len(self._rows) - 1)]
        self.calls += 1
        return type("R", (), {"all": staticmethod(lambda: rows)})()


@pytest.fixture
def wired(monkeypatch):
    """Stub the embedder, the retriever, the runtime toggles and the DB."""
    captured: dict = {}

    monkeypatch.setattr(
        deps,
        "get_embedder",
        lambda: type("E", (), {"embed_one": staticmethod(lambda t: [0.0] * 1536)})(),
    )
    monkeypatch.setattr(
        deps,
        "get_runtime_retrieval_config",
        lambda: type(
            "C",
            (),
            {
                "effective_search_mode": staticmethod(lambda: "vector"),
                "effective_rerank": staticmethod(lambda: False),
            },
        )(),
    )

    async def fake_retrieve(**kwargs):
        captured.update(kwargs)
        return _Result(chunks=captured.get("_chunks", [_Chunk(1), _Chunk(2, distance=0.5)]))

    import app.generation.rag.retrieval.pipeline as pipeline

    monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)

    def make(rows):
        session = _Session(rows)
        monkeypatch.setattr(deps, "get_async_session_factory", lambda: lambda: session)
        return session

    return captured, make


async def test_search_filters_the_task_corpus_of_the_budget_collection(wired):
    captured, make = wired
    make([[(1, "BUD-1", "Fleet & Routing")], [("BUD-1", "Fleet & Routing", 240.0, 8)]])

    await deps.get_budget_search_backend()("logistics routing backend", sectors=["logistics"])

    # The hours only exist on the task corpus, and only inside the budget
    # collection — get either wrong and every reference_amounts comes back empty.
    assert captured["chunk_types"] == ["historical_task"]
    assert captured["collection"].value == "budget"
    assert captured["sectors"] == ["logistics"]


async def test_filters_reach_the_retriever(wired):
    captured, make = wired
    make([[(1, "BUD-1", "Fleet & Routing")], [("BUD-1", "Fleet & Routing", 240.0, 8)]])

    await deps.get_budget_search_backend()("q", year_min=2022, year_max=2024)

    assert captured["project_year_min"] == 2022
    assert captured["project_year_max"] == 2024


async def test_search_over_fetches_tasks_because_they_collapse_into_modules(wired):
    captured, make = wired
    make([[(1, "BUD-1", "Fleet & Routing")], [("BUD-1", "Fleet & Routing", 240.0, 8)]])

    await deps.get_budget_search_backend()("q", top_k=5)

    # Five modules wanted means many more tasks asked for: several tasks of the
    # same module match the same query and dedupe down to one reference.
    assert captured["top_k"] > 5
    assert captured["rerank_top_n"] == captured["top_k"]


async def test_items_are_modules_priced_at_the_sum_of_all_their_tasks(wired):
    _captured, make = wired
    make(
        [
            [(1, "BUD-1", "Fleet & Routing"), (2, "BUD-1", "Fleet & Routing")],
            [("BUD-1", "Fleet & Routing", 240.0, 8)],
        ]
    )

    items = await deps.get_budget_search_backend()("q")

    # Two retrieved tasks, one module: a single reference worth what the WHOLE
    # module cost (240h across 8 tasks), not the 20h of the task that matched.
    assert len(items) == 1
    assert items[0]["estimated_hours"] == 240
    assert items[0]["budget_id"] == "BUD-1/Fleet & Routing"
    assert "8 tasks" in items[0]["content_preview"]
    # The closest matching task represents the module, for traceability.
    assert items[0]["id"] == 1
    assert items[0]["distance"] == 0.4


async def test_distinct_modules_come_back_separately_best_match_first(wired):
    _captured, make = wired
    make(
        [
            [(1, "BUD-1", "Fleet & Routing"), (2, "BUD-2", "Analytics & Reporting")],
            [
                ("BUD-1", "Fleet & Routing", 240.0, 8),
                ("BUD-2", "Analytics & Reporting", 110.0, 4),
            ],
        ]
    )

    items = await deps.get_budget_search_backend()("q")

    assert [i["estimated_hours"] for i in items] == [240, 110]


async def test_no_retrieval_hits_returns_nothing_rather_than_inventing(wired):
    captured, make = wired
    captured["_chunks"] = []
    make([[], []])

    assert await deps.get_budget_search_backend()("nothing matches this") == []


async def test_a_module_with_no_recorded_hours_is_dropped(wired):
    _captured, make = wired
    make([[(1, "BUD-1", "Fleet & Routing")], [("BUD-1", "Fleet & Routing", 0.0, 3)]])

    # Zero hours is not a reference; passing it on would price a subsystem at 0.
    assert await deps.get_budget_search_backend()("q") == []


async def test_search_fails_loudly_without_an_embedder(wired):
    _captured, make = wired
    make([[], []])
    import app.dependencies as d

    object.__setattr__(d, "get_embedder", lambda: None)
    with pytest.raises(RuntimeError, match="Embedding service"):
        await d.get_budget_search_backend()("q")


async def test_hits_whose_module_cannot_be_resolved_yield_nothing(wired):
    _captured, make = wired
    # Retrieval hit a chunk with no module metadata (a base-corpus component, say):
    # there is no subsystem to price, so it must drop out rather than be reported
    # at whatever hours happen to be on the row.
    make([[(99, "BUD-1", None)], []])

    assert await deps.get_budget_search_backend()("q") == []


def test_async_client_is_none_without_an_openai_key(monkeypatch):
    # The agent path is OpenAI-specific (Responses API) and has no fallback
    # provider, so a missing key must surface as None for the CLI to report —
    # not as a client that fails on first use.
    settings = deps.get_settings()
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    deps.get_async_openai_client.cache_clear()
    try:
        assert deps.get_async_openai_client() is None
    finally:
        deps.get_async_openai_client.cache_clear()


def test_async_client_is_built_when_a_key_is_configured(monkeypatch):
    from openai import AsyncOpenAI

    settings = deps.get_settings()
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-not-a-real-key")
    deps.get_async_openai_client.cache_clear()
    try:
        assert isinstance(deps.get_async_openai_client(), AsyncOpenAI)
    finally:
        deps.get_async_openai_client.cache_clear()
