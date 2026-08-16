"""Tests for the RAG flow orchestrated in the conductor (Session 9).

Every collaborator is a double: what is under test is the wiring and the
policy, not the stages (each has its own test module). The two assertions that
matter most are negative ones — the generator must NOT be called when retrieval
soft-fails, and the whole flow must NOT run twice for the same idempotency key.
"""

from __future__ import annotations

import pytest

from app.domain.estimation_service import EstimationService, RagFlowUnavailable
from app.domain.schemas.rag_estimate import Assumption, CostComponent, Estimate, SourceCitation
from app.generation.rag.context_assembler import ContextAssembler
from app.generation.rag.generator import GenerationOutcome
from app.generation.rag.schemas import (
    EstimationQuery,
    ReformulationResult,
    RetrievalFilters,
    RetrievalResult,
    RetrievedChunk,
)


def make_chunk(chunk_id: int, distance: float = 0.35) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=f"Component {chunk_id}\nEstimated hours: 120",
        chunk_type="budget_component",
        distance=distance,
        sector="ecommerce",
        project_year=2023,
        country="DE",
        budget_id="BUD-2024-006",
        component_id=f"C-{chunk_id}",
    )


def make_estimate() -> Estimate:
    return Estimate(
        total_engineer_days=68,
        cost_breakdown=[CostComponent(name="Vendor payouts", engineer_days=68, sources=[1])],
        duration_weeks=9,
        sources=[SourceCitation(source_id=1, relevance="primary", used_for="Vendor payouts")],
        assumptions=[Assumption(description="No app", impact="low", rationale="not requested")],
        confidence="medium",
        reasoning="Based on source 1.",
    )


class FakeReformulator:
    def __init__(self, result: ReformulationResult | None = None) -> None:
        self.result = result or ReformulationResult(
            search_text="multi-vendor marketplace with vendor payouts.",
            query=EstimationQuery(function="multi-vendor marketplace", sector="ecommerce"),
        )
        self.calls: list[str] = []

    def reformulate(self, transcript: str) -> ReformulationResult:
        self.calls.append(transcript)
        return self.result


class FakeRetriever:
    def __init__(self, chunks: list[RetrievedChunk] | None = None) -> None:
        self.chunks = [make_chunk(1), make_chunk(2, 0.42)] if chunks is None else chunks
        self.calls: list[dict] = []

    async def retrieve(self, **kwargs) -> RetrievalResult:
        self.calls.append(kwargs)
        return RetrievalResult(
            chunks=self.chunks,
            low_confidence=not self.chunks,
            total_candidates_considered=24,
            search_time_ms=12,
        )


class FakeGenerator:
    def __init__(self, outcome: GenerationOutcome | None = None) -> None:
        self.outcome = outcome or GenerationOutcome(
            estimate=make_estimate(), invalid_citations=[], warnings=[], retried=False
        )
        self.calls: list[dict] = []

    def generate(self, **kwargs) -> GenerationOutcome:
        self.calls.append(kwargs)
        return self.outcome


class FakeIdempotencyStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, payload: str) -> None:
        self.data[key] = payload


def make_service(**overrides) -> EstimationService:
    defaults = dict(
        llm_wrapper=None,
        exact_cache=None,
        query_reformulator=FakeReformulator(),
        retriever=FakeRetriever(),
        context_assembler=ContextAssembler(token_budget=20_000),
        estimate_generator=FakeGenerator(),
        idempotency_store=FakeIdempotencyStore(),
        rag_top_k=10,
        rag_distance_threshold=0.6,
    )
    return EstimationService(**{**defaults, **overrides})


TRANSCRIPT = "Reunión con el cliente. " * 20


async def test_full_flow_returns_a_grounded_estimate_with_its_trace():
    service = make_service()
    response = await service.estimate_from_transcript(TRANSCRIPT)

    assert response.estimate is not None
    assert response.estimate.total_engineer_days == 68
    assert response.low_confidence is False
    assert response.needs_manual_review is False
    assert response.request_id
    assert response.retrieval.chunks_retrieved == 2
    assert response.retrieval.chunks_used == 2
    assert response.retrieval.total_candidates_considered == 24
    assert response.retrieval.best_distance == 0.35
    assert response.retrieval.filters_applied == {"sectors": ["ecommerce"]}


async def test_derived_sector_filter_reaches_the_retriever():
    retriever = FakeRetriever()
    service = make_service(retriever=retriever)
    await service.estimate_from_transcript(TRANSCRIPT)

    call = retriever.calls[0]
    assert call["filters"] == RetrievalFilters(sectors=["ecommerce"])
    assert call["top_k"] == 10
    assert call["distance_threshold"] == 0.6
    # What is embedded is the composed text, never the raw transcript.
    assert call["search_text"] == "multi-vendor marketplace with vendor payouts."


async def test_soft_fail_never_calls_the_generator():
    generator = FakeGenerator()
    service = make_service(retriever=FakeRetriever(chunks=[]), estimate_generator=generator)

    response = await service.estimate_from_transcript(TRANSCRIPT)

    assert generator.calls == [], "no generation without evidence"
    assert response.estimate is None
    assert response.low_confidence is True
    assert response.needs_manual_review is True
    assert "distance threshold" in response.review_reason
    assert response.retrieval.total_candidates_considered == 24


async def test_idempotency_key_replays_the_first_answer_without_re_running():
    reformulator, retriever, generator = FakeReformulator(), FakeRetriever(), FakeGenerator()
    service = make_service(
        query_reformulator=reformulator, retriever=retriever, estimate_generator=generator
    )

    first = await service.estimate_from_transcript(TRANSCRIPT, idempotency_key="abc-123")
    second = await service.estimate_from_transcript(TRANSCRIPT, idempotency_key="abc-123")

    assert first.cached is False
    assert second.cached is True
    assert second.request_id == first.request_id
    assert second.estimate == first.estimate
    assert len(reformulator.calls) == 1
    assert len(retriever.calls) == 1
    assert len(generator.calls) == 1


async def test_a_different_key_runs_the_flow_again():
    generator = FakeGenerator()
    service = make_service(estimate_generator=generator)

    await service.estimate_from_transcript(TRANSCRIPT, idempotency_key="key-1")
    await service.estimate_from_transcript(TRANSCRIPT, idempotency_key="key-2")

    assert len(generator.calls) == 2


async def test_generation_warnings_surface_as_manual_review():
    outcome = GenerationOutcome(
        estimate=make_estimate(),
        invalid_citations=[999],
        warnings=[],
        retried=True,
    )
    service = make_service(estimate_generator=FakeGenerator(outcome))
    response = await service.estimate_from_transcript(TRANSCRIPT)

    assert response.needs_manual_review is True
    assert "999" in response.review_reason
    assert response.estimate is not None


async def test_insufficient_confidence_is_reported_as_low_confidence():
    estimate = make_estimate()
    estimate.confidence = "insufficient"
    estimate.insufficient_context_explanation = "corpus has no comparable project"
    service = make_service(
        estimate_generator=FakeGenerator(
            GenerationOutcome(estimate=estimate, invalid_citations=[], warnings=[], retried=False)
        )
    )
    response = await service.estimate_from_transcript(TRANSCRIPT)

    assert response.low_confidence is True
    assert response.estimate is not None


async def test_missing_collaborators_refuse_to_half_run():
    service = make_service(retriever=None)
    with pytest.raises(RagFlowUnavailable):
        await service.estimate_from_transcript(TRANSCRIPT)
