"""Request and response models for the estimation endpoint.

Session 4 contract: typed form-style request maps to a typed, validated
``EstimationResult`` (structured output via Instructor + Pydantic). Two model
validators enforce business rules that the LLM cannot break:

1. Low-confidence answers (< 30%) must declare it explicitly by starting the
   summary with ``"Out of scope:"``.

The other rule this file used to enforce — that the phases add up to the total —
is no longer a validator: the total is derived from the phases, so it cannot be
broken. See ``EstimationResult``.

When the LLM violates a validator, Instructor re-prompts the model with the
``ValueError`` message until it agrees (up to ``max_retries`` attempts).
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator


class ProjectType(str, Enum):
    MOBILE_APP = "mobile_app"
    WEB_SAAS = "web_saas"
    INTERNAL_TOOL = "internal_tool"
    DATA_PIPELINE = "data_pipeline"


class DetailLevel(str, Enum):
    SUMMARY = "summary"
    MEDIUM = "medium"
    DETAILED = "detailed"


class OutputFormat(str, Enum):
    PHASES_TABLE = "phases_table"
    LINE_ITEMS = "line_items"
    NARRATIVE = "narrative"


class EstimationRequest(BaseModel):
    """Typed payload sent by the business backend or Streamlit form."""

    description: str = Field(
        min_length=20,
        max_length=80000,
        description="Free-text description or transcription of the project to estimate.",
    )
    project_type: ProjectType = Field(description="Coarse-grained project category.")
    detail_level: DetailLevel = Field(description="How deep the estimation should go.")
    output_format: OutputFormat = Field(description="Shape of the rendered estimation.")


# --- Structured response ----------------------------------------------------


OUT_OF_SCOPE_PREFIX = "Out of scope:"
LOW_CONFIDENCE_THRESHOLD = 30


class Phase(BaseModel):
    """One phase in the breakdown of an estimation."""

    name: str = Field(min_length=1, max_length=64)
    duration_weeks: int = Field(ge=1, le=52)
    cost_eur: int = Field(ge=0, le=1_000_000)
    summary: str = Field(min_length=10, max_length=600)


class EstimationResult(BaseModel):
    """Structured estimation.

    ``total_cost_eur`` used to be a field, with a validator checking that the
    phases added up to it and Instructor re-prompting the model when they did
    not. That turned an arithmetic identity into a negotiation, and a measured
    run with ``gpt-4o-mini`` lost it six times in a row (53500≠58500,
    63000≠60000, 65000≠60000, 66000≠60000, 63000≠60000, 64000≠60000): six
    calls, ~111.000 prompt tokens and 22 seconds to produce an HTTP 502.

    It is now DERIVED. The invariant the validator defended — the budget adds
    up — holds by construction instead of by retry, which is the same move the
    project already makes two sessions later: ``calculate_estimate`` prices the
    components in Python, and ``ValidationResult.confidence`` is computed and
    never asked for.

    ``low_confidence_requires_out_of_scope_prefix`` stays, and it is the better
    example of the rule anyway: it is a FORMAT instruction, the kind a re-prompt
    can actually fix, not a sum the model was never going to get right.

    Field order is still deliberate: ``phases`` comes before the totals so the
    LLM commits to the per-phase numbers first (autoregressive generation)
    rather than picking a round total and back-fitting phases to it.
    """

    summary: str = Field(min_length=10, max_length=1200)
    confidence_pct: int = Field(ge=0, le=100)
    phases: list[Phase] = Field(min_length=1, max_length=8)
    total_duration_weeks: int = Field(ge=1, le=104)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost_eur(self) -> int:
        """The budget total, DERIVED rather than asked for.

        Instructor runs in ``Mode.TOOLS``, and a computed field is absent from
        the tool schema the model sees: it cannot get this number wrong because
        nobody asks it for one. It is still present in the JSON response and in
        the OpenAPI document, so the contract the business backend consumes is
        unchanged.
        """
        return sum(p.cost_eur for p in self.phases)

    @model_validator(mode="after")
    def low_confidence_requires_out_of_scope_prefix(self) -> "EstimationResult":
        if self.confidence_pct < LOW_CONFIDENCE_THRESHOLD and not self.summary.startswith(
            OUT_OF_SCOPE_PREFIX
        ):
            raise ValueError(
                f"confidence_pct < {LOW_CONFIDENCE_THRESHOLD} requires summary to "
                f"start with {OUT_OF_SCOPE_PREFIX!r}; refuse the estimation if the "
                f"description is too vague to size"
            )
        return self


class TurnObservation(BaseModel):
    """Per-turn telemetry attached to a conversational response.

    Populated by ``estimate_conversational`` only; the non-conversational
    endpoint leaves ``EstimationResponse.observation`` as ``None``. The stress
    runner reads this field directly from the JSON response — no log parsing.

    ``cache_hit_kind`` is always ``"none"`` for the conversational path
    (sessions bypass both caches by design); the field is kept for symmetry
    with the non-conversational endpoint and to document that choice.
    """

    turn_index: int = Field(ge=1)
    session_id: str
    enriched_transcript_chars: int = Field(ge=0)
    attachments_total_chars: int = Field(ge=0)
    messages_in_window: int = Field(ge=0)
    anchors_count: int = Field(ge=0)
    summary_chars: int = Field(ge=0)
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    cost_usd: float = Field(ge=0)
    latency_ms: int = Field(ge=0)
    cache_hit_kind: Literal["none", "exact", "semantic"] = "none"
    last_resolved_tier: str | None = None


class EstimationResponse(BaseModel):
    """Wraps the validated result, the prompt version that produced it, and
    whether it came from a cache (exact or semantic).

    ``observation`` is populated only by the conversational endpoint
    (``POST /sessions/{id}/estimate``). It carries the per-turn telemetry the
    stress runner needs without contaminating the production contract — older
    callers that ignore the field keep working.
    """

    result: EstimationResult
    prompt_version: str
    cached: bool = False
    observation: TurnObservation | None = None


from app.domain.schemas.acb import BossTrace  # noqa: E402


class ACBResponse(EstimationResponse):
    """Conversational response with the Actor-Critic-Boss audit trail.

    Same shape as ``EstimationResponse`` plus the ``acb`` field carrying the
    iteration log. The UI uses the trail to render an expander showing what
    the Critic flagged at each step and how the Boss decided.
    """

    acb: BossTrace
