"""Flow tests for the end-to-end orchestrator (Session 9).

Every component is mocked: we validate the wiring (which stage runs, in what
order, and the soft-fail short-circuit), not the components themselves.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.dependencies as deps
from app.generation.rag import estimator as orch
from app.generation.rag.schemas import (
    Estimate,
    EstimationQuery,
    RetrievalResult,
    RetrievedChunk,
    SourceCitation,
    SourceReference,
    TaskItem,
    WorkModule,
)

_SETTINGS = SimpleNamespace(
    REFORMULATION_MODEL="gpt-5-mini",
    GENERATION_MODEL="gpt-5",
    GENERATION_REASONING_EFFORT="high",
    GENERATION_MAX_TOKENS=64_000,
    RETRIEVAL_TOP_K=10,
    RETRIEVAL_DISTANCE_THRESHOLD=0.6,
    MAX_CONTEXT_TOKENS=100_000,
    RETRIEVAL_RECALL_TOP_K=50,
    RERANK_TOP_N=5,
    RRF_K=60,
)


class CharEncoder:
    def encode(self, text: str) -> list[str]:
        return list(text)


class RecordingStore:
    def __init__(self):
        self.saved: dict[str, Estimate] = {}

    def get(self, key):
        return self.saved.get(key)

    def set(self, key, estimate):
        self.saved[key] = estimate


def _chunk(chunk_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content="Component: Checkout\nEstimated hours: 140",
        sector="ecommerce",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.42,
    )


def _good_estimate() -> Estimate:
    return Estimate(
        total_engineer_days=18,
        duration_weeks=4,
        modules=[
            WorkModule(
                name="Checkout",
                tasks=[
                    TaskItem(
                        name="Cart & payment flow",
                        sources=[SourceReference(chunk_id=1, evidence="Checkout flow: 140h")],
                        grounded=True,
                        engineer_days=18,
                    )
                ],
            )
        ],
        sources=[SourceCitation(source_id=1, relevance="primary", used_for="checkout")],
        assumptions=[],
        confidence="high",
        reasoning="Grounded in BUD-2024-005.",
    )


@pytest.fixture
def wire(monkeypatch):
    """Wire the orchestrator with mocked stages; return a call counter."""
    calls = {"reformulate": 0, "search": 0, "generate": 0, "embed": 0}
    store = RecordingStore()

    def _wire(*, retrieval: RetrievalResult, estimate: Estimate | None = None):
        async def fake_reformulate(transcript):
            calls["reformulate"] += 1
            return EstimationQuery(function="ecommerce storefront", sector="ecommerce")

        async def fake_retrieve(**kwargs):
            calls["search"] += 1
            return retrieval

        async def fake_generate(context_block, structured_query):
            calls["generate"] += 1
            return estimate

        def fake_embed(text):
            calls["embed"] += 1
            return [0.0] * 1536

        fake_runtime = SimpleNamespace(
            effective_search_mode=lambda: "vector",
            effective_rerank=lambda: False,
        )

        monkeypatch.setattr(orch, "get_settings", lambda: _SETTINGS)
        monkeypatch.setattr(orch, "reformulate_query", fake_reformulate)
        monkeypatch.setattr(orch, "retrieve", fake_retrieve)
        monkeypatch.setattr(orch, "generate_estimate", fake_generate)
        monkeypatch.setattr(deps, "get_embedder", lambda: SimpleNamespace(embed_one=fake_embed))
        monkeypatch.setattr(deps, "get_token_encoder", lambda: CharEncoder())
        monkeypatch.setattr(deps, "get_idempotency_store", lambda: store)
        monkeypatch.setattr(deps, "get_runtime_retrieval_config", lambda: fake_runtime)
        return calls, store

    return _wire


async def test_happy_path_runs_all_stages(wire):
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    calls, _store = wire(retrieval=retrieval, estimate=_good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert result.confidence == "high"
    assert result.total_engineer_days == 18
    assert calls == {"reformulate": 1, "search": 1, "generate": 1, "embed": 1}


async def test_soft_fail_skips_generation(wire):
    retrieval = RetrievalResult(chunks=[], low_confidence=True, candidates_evaluated=7)
    calls, _store = wire(retrieval=retrieval, estimate=_good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert result.confidence == "insufficient"
    assert result.total_engineer_days is None
    assert result.insufficient_context_explanation
    assert calls["generate"] == 0  # generator never called on soft-fail


async def test_generate_estimate_passes_reasoning_token_budget(monkeypatch):
    """gpt-5 reasoning tokens count against max_tokens; _generate must pass the
    configured ceiling (and the reasoning effort) to the wrapper, or the call
    truncates with finish_reason='length'."""
    captured: dict = {}

    def fake_complete_structured(**kwargs):
        captured.update(kwargs)
        return _good_estimate(), {}

    wrapper = SimpleNamespace(complete_structured=fake_complete_structured)
    monkeypatch.setattr(orch, "get_settings", lambda: _SETTINGS)
    monkeypatch.setattr(deps, "get_llm_wrapper", lambda: wrapper)

    estimate = await orch.generate_estimate(
        '<source id="1">x</source>', EstimationQuery(function="ecommerce storefront")
    )

    assert estimate.confidence == "high"
    assert captured["max_tokens"] == _SETTINGS.GENERATION_MAX_TOKENS
    assert captured["reasoning_effort"] == "high"
    assert captured["model_override"] == "gpt-5"


async def test_idempotency_hit_short_circuits_pipeline(wire):
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    calls, store = wire(retrieval=retrieval, estimate=_good_estimate())

    first = await orch.estimate_from_transcript("x" * 200, idempotency_key="k1")
    assert calls["generate"] == 1
    assert store.saved.get("k1") is not None

    second = await orch.estimate_from_transcript("x" * 200, idempotency_key="k1")
    assert second == first
    # No stage re-ran on the cached call.
    assert calls == {"reformulate": 1, "search": 1, "generate": 1, "embed": 1}


# --- Session 11: per-line citation verification inside the pipeline ----------


def _mixed_estimate() -> Estimate:
    """One well-grounded line plus one citing a chunk that was never retrieved."""
    return Estimate(
        total_engineer_days=25,
        duration_weeks=5,
        modules=[
            WorkModule(
                name="Checkout",
                tasks=[
                    TaskItem(
                        name="Cart & payment flow",
                        sources=[SourceReference(chunk_id=1, evidence="Checkout flow: 140h")],
                        grounded=True,
                        engineer_days=18,
                    ),
                    TaskItem(
                        name="Fraud scoring",
                        sources=[SourceReference(chunk_id=42, evidence="Fraud rules: 60h")],
                        grounded=True,
                        engineer_days=7,
                    ),
                ],
            )
        ],
        sources=[SourceCitation(source_id=1, relevance="primary", used_for="checkout")],
        assumptions=[],
        confidence="high",
        reasoning="Grounded in BUD-2024-005.",
    )


def _wire_retry(monkeypatch, wire, first: Estimate, second: Estimate):
    """Wire the pipeline so generation returns ``first`` and the retry ``second``."""
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    calls, store = wire(retrieval=retrieval, estimate=first)
    retries = {"n": 0}

    async def fake_retry(context_block, structured_query, *, feedback=None, include_hours=True):
        retries["n"] += 1
        return second

    monkeypatch.setattr(orch, "_generate", fake_retry)
    return calls, retries


async def test_dangling_citation_triggers_one_corrective_retry(wire, monkeypatch):
    calls, retries = _wire_retry(monkeypatch, wire, _mixed_estimate(), _good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert retries["n"] == 1  # exactly one corrective retry
    assert calls["generate"] == 1
    assert result.total_engineer_days == 18
    assert result.modules[0].tasks[0].grounded is True


async def test_unrepaired_dangling_citation_is_demoted_instead_of_served(wire, monkeypatch):
    # The model keeps citing id 42 after the retry: the line must not reach the
    # client carrying a citation that does not resolve, nor a number backing it.
    calls, retries = _wire_retry(monkeypatch, wire, _mixed_estimate(), _mixed_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    assert retries["n"] == 1
    fraud = result.modules[0].tasks[1]
    assert fraud.grounded is False
    assert fraud.sources == []
    assert fraud.engineer_days is None
    # The surviving line keeps its hours and the total is re-derived from them.
    assert result.modules[0].tasks[0].engineer_days == 18
    assert result.total_engineer_days == 18


async def test_served_estimate_resolves_the_document_of_every_citation(wire):
    retrieval = RetrievalResult(chunks=[_chunk(1)], low_confidence=False, candidates_evaluated=5)
    wire(retrieval=retrieval, estimate=_good_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    # _chunk() carries no budget_id, so the resolved value is the empty string —
    # the point is that it comes from the chunk, never from the model.
    assert result.modules[0].tasks[0].sources[0].document_id == ""


async def test_citation_report_is_logged_correlated_by_request_id(wire, monkeypatch):
    import structlog

    _wire_retry(monkeypatch, wire, _mixed_estimate(), _mixed_estimate())

    with structlog.testing.capture_logs() as logs:
        await orch.estimate_from_transcript("x" * 200)

    reports = [entry for entry in logs if entry["event"] == "citation_report"]
    # Logged once, after the retry had its chance, describing what the model produced.
    assert len(reports) == 1
    report = reports[0]
    assert report["grounded"] == 1
    assert report["dangling"] == 1
    assert report["dangling_source_ids"] == [42]
    assert report["retried"] is True
    assert report["request_id"]
    assert report["log_level"] == "warning"


async def test_coherence_repair_output_also_goes_through_the_citation_policy(wire, monkeypatch):
    """A repaired generation is a fresh one: it cannot skip the citation policy.

    Reaching the repair branch needs an estimate that SURVIVES the policy and is
    still incoherent — `insufficient` carrying a line grounded in a chunk that was
    really retrieved. The repair then returns a coherent estimate whose second line
    cites a chunk that was never retrieved; only re-applying the policy catches it.
    """
    incoherent_but_grounded = Estimate(
        confidence="insufficient",
        reasoning="r",
        total_engineer_days=18,
        insufficient_context_explanation="numbers present while insufficient",
        modules=[
            WorkModule(
                name="Checkout",
                tasks=[
                    TaskItem(
                        name="Cart & payment flow",
                        sources=[SourceReference(chunk_id=1, evidence="Checkout flow: 140h")],
                        grounded=True,
                        engineer_days=18,
                    )
                ],
            )
        ],
    )
    _wire_retry(monkeypatch, wire, incoherent_but_grounded, _mixed_estimate())

    result = await orch.estimate_from_transcript("x" * 200)

    # The repair produced a line citing chunk 42, never retrieved. The policy ran
    # again on that fresh output, so it reaches the client demoted, not cited.
    assert result.confidence == "high"
    fraud = result.modules[0].tasks[1]
    assert fraud.grounded is False
    assert fraud.sources == []
    assert fraud.engineer_days is None
    assert result.total_engineer_days == 18
