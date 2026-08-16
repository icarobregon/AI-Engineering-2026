"""Tests for the Generation stage (Session 9): citations and coherence."""

from __future__ import annotations

from app.domain.schemas.rag_estimate import Assumption, CostComponent, Estimate, SourceCitation
from app.generation.rag.context_assembler import ContextAssembler
from app.generation.rag.generator import (
    EstimateGenerator,
    check_coherence,
    validate_citations,
)
from app.generation.rag.schemas import EstimationQuery, RetrievedChunk


def make_estimate(**overrides) -> Estimate:
    base = dict(
        total_engineer_days=100,
        cost_breakdown=[CostComponent(name="Backend", engineer_days=100, sources=[1])],
        duration_weeks=10,
        sources=[SourceCitation(source_id=1, relevance="primary", used_for="Backend")],
        assumptions=[Assumption(description="No mobile", impact="low", rationale="not requested")],
        confidence="medium",
        reasoning="Based on source 1.",
        insufficient_context_explanation=None,
    )
    return Estimate(**{**base, **overrides})


def make_context(ids: list[int]) -> "AssembledContext":  # noqa: F821 — returned by the assembler
    chunks = [
        RetrievedChunk(
            id=i,
            content=f"Component {i}\nEstimated hours: 80",
            chunk_type="budget_component",
            distance=0.3,
            sector="ecommerce",
            project_year=2023,
        )
        for i in ids
    ]
    return ContextAssembler(token_budget=20_000).assemble(chunks)


class FakeResponsesClient:
    """Returns a scripted Estimate per call, recording the prompts it saw."""

    def __init__(self, estimates: list[Estimate]) -> None:
        self.estimates = estimates
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.estimates[min(len(self.calls) - 1, len(self.estimates) - 1)]


def test_validate_citations_flags_ids_that_were_never_retrieved():
    estimate = make_estimate(
        sources=[SourceCitation(source_id=412, relevance="primary", used_for="Backend")],
        cost_breakdown=[CostComponent(name="Backend", engineer_days=100, sources=[1, 999])],
    )
    assert validate_citations(estimate, {1, 2, 3}) == [412, 999]


def test_validate_citations_accepts_a_fully_grounded_estimate():
    assert validate_citations(make_estimate(), {1, 2}) == []


def test_insufficient_confidence_must_not_carry_numbers():
    warnings = check_coherence(
        make_estimate(confidence="insufficient", insufficient_context_explanation="no data")
    )
    assert any("numeric fields are populated" in w for w in warnings)


def test_insufficient_confidence_requires_an_explanation():
    warnings = check_coherence(
        make_estimate(
            confidence="insufficient",
            total_engineer_days=None,
            duration_weeks=None,
            insufficient_context_explanation=None,
        )
    )
    assert any("without an explanation" in w for w in warnings)


def test_breakdown_that_does_not_add_up_is_flagged():
    warnings = check_coherence(
        make_estimate(
            total_engineer_days=100,
            cost_breakdown=[CostComponent(name="Backend", engineer_days=40, sources=[1])],
        )
    )
    assert any("breakdown sums to 40" in w for w in warnings)


def test_component_without_sources_is_flagged():
    warnings = check_coherence(
        make_estimate(cost_breakdown=[CostComponent(name="Backend", engineer_days=100, sources=[])])
    )
    assert any("components with no source" in w for w in warnings)


def test_a_clean_estimate_produces_no_warnings():
    assert check_coherence(make_estimate()) == []


def test_invalid_citations_trigger_exactly_one_retry_with_the_ids_listed():
    bad = make_estimate(
        sources=[SourceCitation(source_id=999, relevance="primary", used_for="Backend")],
        cost_breakdown=[CostComponent(name="Backend", engineer_days=100, sources=[999])],
    )
    good = make_estimate()
    client = FakeResponsesClient([bad, good])
    generator = EstimateGenerator(client, model="gpt-5", reasoning_effort="medium")

    outcome = generator.generate(
        context=make_context([1, 2]),
        query=EstimationQuery(function="marketplace with payouts"),
        search_text="marketplace with payouts",
    )

    assert len(client.calls) == 2
    assert outcome.retried is True
    assert outcome.invalid_citations == []
    assert outcome.needs_manual_review is False
    # The corrective prompt must name the offending ids.
    assert "999" in client.calls[1]["user_content"]


def test_still_invalid_after_the_retry_flags_manual_review_without_dropping_it():
    bad = make_estimate(
        sources=[SourceCitation(source_id=999, relevance="primary", used_for="Backend")],
        cost_breakdown=[CostComponent(name="Backend", engineer_days=100, sources=[999])],
    )
    client = FakeResponsesClient([bad, bad])
    generator = EstimateGenerator(client, model="gpt-5", reasoning_effort="medium")

    outcome = generator.generate(
        context=make_context([1, 2]),
        query=EstimationQuery(function="marketplace with payouts"),
        search_text="marketplace with payouts",
    )

    assert len(client.calls) == 2, "no third attempt"
    assert outcome.invalid_citations == [999]
    assert outcome.needs_manual_review is True
    assert "never retrieved" in outcome.review_reason
    assert outcome.estimate is not None, "a flagged estimate still reaches the reviewer"


def test_generation_passes_reasoning_effort_and_the_context_block():
    client = FakeResponsesClient([make_estimate()])
    generator = EstimateGenerator(client, model="gpt-5", reasoning_effort="high")
    generator.generate(
        context=make_context([1]),
        query=EstimationQuery(function="marketplace"),
        search_text="marketplace",
    )
    call = client.calls[0]
    assert call["reasoning_effort"] == "high"
    assert call["model"] == "gpt-5"
    assert '<source id="1"' in call["user_content"]


def test_fallback_path_without_structured_query_still_generates():
    client = FakeResponsesClient([make_estimate()])
    generator = EstimateGenerator(client, model="gpt-5", reasoning_effort="medium")
    outcome = generator.generate(
        context=make_context([1]), query=None, search_text="multi-vendor marketplace"
    )
    assert outcome.estimate is not None
    assert "multi-vendor marketplace" in client.calls[0]["user_content"]
