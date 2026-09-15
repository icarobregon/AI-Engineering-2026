"""The HTTP contract of the graph-backed estimate (Session 13).

The point of this file is that it looks like the ones that came before it. The
business backend sends a transcript and receives a structured estimate with its
``status``; that the service now runs a graph underneath instead of a loop is an
implementation detail of the AI service, and the day the graph is retired the
contract does not move.
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
            "Sending it again returns the result already computed for it (or "
            "resumes it if it never finished) rather than estimating twice — so "
            "a retry is safe. To estimate the same project again, send a new id."
        ),
    )


class GraphEstimateResponse(BaseModel):
    estimate: Optional[dict] = Field(description="The consolidated estimate.")
    status: Literal["validated", "needs_review"] = Field(
        description="Whether the guardrails passed or a human has to look at it."
    )
    estimation_id: str = Field(description="The thread_id this run was checkpointed under.")
    errors: list[str] = Field(
        default_factory=list,
        description="What degraded or failed validation. Empty on a clean run.",
    )
