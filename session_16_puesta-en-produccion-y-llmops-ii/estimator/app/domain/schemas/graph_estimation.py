"""The HTTP contract of the graph-backed estimate (Sessions 13-14).

The point of this file is that it still looks like the ones that came before it.
The business backend sends a transcript and receives a structured estimate with
its ``status``; that the service now runs a multi-agent system underneath
instead of a loop is an implementation detail of the AI service.

Session 14 adds one thing and it is deliberately small: ``status`` gains the
value ``awaiting_human_review``. That is a **new value of a field that already
existed**, so the backend needs a new branch, not a new integration — and the
reviewer's authorisation, the notification and the approval history stay in the
business backend, where those decisions belong.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field


class GraphEstimateRequest(BaseModel):
    transcript: str = Field(min_length=1, description="Raw meeting transcript.")
    estimation_id: Optional[str] = Field(
        default=None,
        description=(
            "Business id of this estimation, used as the graph's thread_id. "
            "Sending it again returns what is already known for it — the "
            "finished estimate, or the pending human review — rather than "
            "estimating twice, so a retry is safe. To estimate the same project "
            "again, send a new id."
        ),
    )


class HumanDecision(BaseModel):
    """What a reviewer sends back to release a paused estimation."""

    # Dos, no tres. "adjust" —un total suelto— murió en la Sesión 15: el revisor
    # pone precio COMPONENTE A COMPONENTE y el total se deriva de la suma, así
    # que aprobar con cambios ES aprobar. Este esquema valida peticiones
    # ENTRANTES, no relee checkpoints: los `human_decision` escritos antes viven
    # en el estado como dicts y nunca vuelven a pasar por aquí, así que conservar
    # el valor sólo habría dejado aceptando una acción que ningún cliente puede
    # producir ya.
    action: Literal["approve", "reject"]
    component_hours: Optional[dict[str, Annotated[float, Field(ge=0)]]] = Field(
        default=None,
        description=(
            "The hours the reviewer decided on, keyed by `component_id`. Applied "
            "on approve AND on reject: a rejection is also evidence of what was "
            "considered, and throwing it away loses the gap between what the "
            "system proposed and what a person thought, which is what the "
            "confidence threshold gets calibrated against. Keyed by id and never "
            "by name or position — a line matched by a model-authored name is "
            "how seven components once came back flagged as unbacked. The TOTAL "
            "is never sent: it is derived from these, which is what makes the "
            "bottom line and the breakdown incapable of disagreeing."
        ),
    )
    comment: Optional[str] = Field(default=None, description="Why, for the record.")
    reviewer_id: Optional[str] = Field(
        default=None, description="Who decided. Authorisation itself lives in the business backend."
    )


class GraphEstimateResponse(BaseModel):
    estimate: Optional[dict] = Field(description="The consolidated estimate.")
    status: Literal[
        "validated", "needs_review", "awaiting_human_review", "routing_budget_exhausted"
    ] = Field(
        description=(
            "Whether the estimate passed, needs a look, is waiting on a human "
            "decision, or ran out of routing budget before finishing."
        )
    )
    estimation_id: str = Field(description="The thread_id this run was checkpointed under.")
    errors: list[str] = Field(
        default_factory=list,
        description="What degraded or failed validation. Empty on a clean run.",
    )
    review_payload: Optional[dict] = Field(
        default=None,
        description=(
            "Present only with status 'awaiting_human_review': everything the "
            "reviewer needs to decide — the estimate, its confidence, what "
            "triggered the pause and the historical band to judge it against."
        ),
    )


class CommercialProposal(BaseModel):
    """The client-facing document written from a finished estimate (Session 15).

    Every field here is rendered by the business backend, which is the whole
    reason the list is this short. The reference implementation asks its model
    for five fields and its client keeps two — the other three are generated,
    paid for and thrown away on every run.

    There is deliberately **no total** in this schema. The hours belong to
    ``calculate_estimate`` and travel in the estimate itself; asking the writer
    for them again would give the proposal its own copy of a number that can
    then disagree with the estimate it is describing.
    """

    title: str = Field(description="Proposal title, one line, naming the project.")
    executive_summary: str = Field(description="One paragraph: what gets built and what it takes.")
    scope: list[str] = Field(description="What is included, one line per component.")
    assumptions: list[str] = Field(
        description=(
            "Assumptions and caveats, including components with no historical "
            "precedent and the validator's concerns."
        )
    )
    body_markdown: str = Field(description="The body of the document, in simple markdown.")
