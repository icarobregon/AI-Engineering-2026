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

from typing import Literal, Optional

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

    action: Literal["approve", "adjust", "reject"]
    adjusted_hours: Optional[float] = Field(
        default=None,
        ge=0,
        description="The total the reviewer decided on. Only read when action is 'adjust'.",
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
