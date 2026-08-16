"""Contract of the RAG estimation endpoint (Session 9).

Deliberately NOT an evolution of ``EstimationResult`` (Session 4). That schema
is a public contract with two business validators and a field order tuned for
Instructor; this one answers a different question — "what do the historical
budgets say this project costs, and which ones say it" — and its centre of
gravity is traceability: every number carries the source ids that support it,
every gap is an explicit assumption, and "not enough evidence" is a first-class
answer rather than a low confidence percentage.

Schema constraints (``ge``, ``min_length``, …) are absent on purpose: this model
is sent to OpenAI with ``strict: True``, which rejects most JSON Schema
validation keywords. Invariants that matter are re-checked in Python by
``validate_estimate`` in the generator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceCitation(BaseModel):
    """One historical chunk the estimate leans on, and how much."""

    source_id: int
    relevance: Literal["primary", "supporting", "tangential"]
    used_for: str = Field(description="Which component this source informed")


class Assumption(BaseModel):
    """A gap the historical data does not cover, made explicit."""

    description: str
    impact: Literal["high", "medium", "low"]
    rationale: str


class CostComponent(BaseModel):
    """A line of the estimate, with the sources that back its number."""

    name: str
    engineer_days: int
    sources: list[int] = Field(description="Source ids that support this component")


class Estimate(BaseModel):
    """The structured estimate produced from retrieved historical evidence."""

    total_engineer_days: int | None
    cost_breakdown: list[CostComponent]
    duration_weeks: int | None
    sources: list[SourceCitation]
    assumptions: list[Assumption]
    confidence: Literal["high", "medium", "low", "insufficient"]
    reasoning: str
    insufficient_context_explanation: str | None = Field(
        default=None,
        description="If confidence is 'insufficient', explain what is missing",
    )


class EstimateRequest(BaseModel):
    """Payload for ``POST /v1/estimate/from-transcript``.

    Deliberately minimal: the transcript and nothing else. Every knob that
    could change the answer (top_k, threshold, filters, models) is server-side
    configuration, so two identical transcripts cannot produce different
    estimates because a caller passed different parameters.
    """

    transcript: str = Field(min_length=100, max_length=50_000)
    idempotency_key: str | None = Field(default=None, max_length=128)


class RetrievalTrace(BaseModel):
    """What retrieval did, surfaced to the caller for auditability."""

    chunks_retrieved: int
    chunks_used: int
    total_candidates_considered: int
    best_distance: float | None = None
    worst_distance: float | None = None
    filters_applied: dict = Field(default_factory=dict)
    used_reformulation_fallback: bool = False
    search_text: str | None = None


class EstimateResponse(BaseModel):
    """Envelope returned by ``POST /v1/estimate/from-transcript``.

    ``estimate`` is ``None`` exactly when ``low_confidence`` is true and
    retrieval found nothing: no context, no generation, no invented numbers.
    """

    request_id: str
    estimate: Estimate | None
    low_confidence: bool
    needs_manual_review: bool
    review_reason: str | None = None
    retrieval: RetrievalTrace
    cached: bool = False
