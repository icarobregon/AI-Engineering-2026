"""What the agents are allowed to return.

These are the agent-level contracts, not the HTTP one (that lives in
``app/domain/schemas/graph_estimation.py``). They stay deliberately small: what
an agent puts in the state is serialised into a checkpoint after every step, so
a schema that invites the model to be chatty is paid for on every write.

One shape changed in Session 14. The estimate's HOURS no longer come from the
model: ``estimate_generator`` is granted ``calculate_estimate`` and the tool does
the arithmetic, so the model is asked only for the prose it is actually good at
— which component the evidence backs and why. ``DraftEstimate`` survives as the
shape of the ASSEMBLED result the agent writes to the state, so everything
downstream of it (the validator's id join, the HTTP response) is unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementList(BaseModel):
    """`requirements_extractor`, first pass: the transcript reduced to what must be built."""

    requirements: list[str] = Field(
        description="One line per requirement stated or implied in the meeting."
    )


class ClassifiedComponent(BaseModel):
    name: str = Field(description="The component as the meeting named it.")
    category: str = Field(
        description="Kind of work: backend, integration, mobile, frontend, "
        "analytics, infrastructure, data or other."
    )
    search_query: str = Field(
        description=(
            "The same component described IN ENGLISH for searching historical "
            "budgets: the work, its technologies and its scope, as a short "
            "description rather than a question. The corpus is written in "
            "English and a query in another language retrieves measurably worse."
        )
    )


class ComponentList(BaseModel):
    """`requirements_extractor`, second pass: requirements grouped into units of work."""

    components: list[ClassifiedComponent]


class ComponentNarrative(BaseModel):
    """The model's account of ONE component. No hours: the tool owns those."""

    component_id: str = Field(
        description="The `id:` value of the component this line describes, e.g. 'c1'."
    )
    rationale: str = Field(
        description="Which historical references back this component, in one line. "
        "Say so plainly when there are none."
    )


class EstimateNarrative(BaseModel):
    """`estimate_generator`: everything about the estimate except the numbers."""

    project: str = Field(description="Short name of the project being estimated.")
    components: list[ComponentNarrative]
    notes: str = Field(description="Caveats and gaps the human should check.")


class EstimatedComponent(BaseModel):
    component_id: str = Field(
        description="The `id:` value of the component this line estimates, e.g. 'c1'."
    )
    name: str
    estimated_hours: float = Field(description="Engineer-hours, as calculate_estimate priced them.")
    grounded: bool = Field(description="False when no historical reference backed this component.")
    rationale: str = Field(description="Which references back this number, in one line.")


class DraftEstimate(BaseModel):
    """The consolidated estimate `estimate_generator` writes to the state."""

    project: str
    components: list[EstimatedComponent]
    total_hours: float
    notes: str = Field(description="Caveats and gaps the human should check.")


class ValidationResult(BaseModel):
    """`coherence_validator`: the coherence verdict and the confidence signal.

    ``confidence`` is COMPUTED, never asked for. A model asked to score its own
    output rates what it just said highly, and the human gate hangs off this
    number — a trigger you cannot reproduce is a trigger you cannot deliver.
    """

    is_coherent: bool
    confidence: float = Field(ge=0.0, le=1.0)
    concerns: list[str]
    reasoning: str
