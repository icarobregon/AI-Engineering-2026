"""What the LLM nodes are allowed to return.

These are the node-level contracts, not the HTTP one (that lives in
``app/domain/schemas/graph_estimation.py``). They stay deliberately small: what
a node puts in the state is serialised into a checkpoint after every step, so a
schema that invites the model to be chatty is paid for on every write.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementList(BaseModel):
    """`extract_requirements`: the transcript reduced to what must be built."""

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
    """`classify_components`: requirements grouped into units of work."""

    components: list[ClassifiedComponent]


class EstimatedComponent(BaseModel):
    component_id: str = Field(
        description="The `id:` value of the component this line estimates, e.g. 'c1'."
    )
    name: str
    estimated_hours: float = Field(
        description="Engineer-hours, grounded in the historical references given."
    )
    grounded: bool = Field(description="False when no historical reference backed this component.")
    rationale: str = Field(description="Which references back this number, in one line.")


class DraftEstimate(BaseModel):
    """`generate_estimate`: the consolidated estimate, before validation."""

    project: str
    components: list[EstimatedComponent]
    total_hours: float
    notes: str = Field(description="Caveats and gaps the human should check.")
