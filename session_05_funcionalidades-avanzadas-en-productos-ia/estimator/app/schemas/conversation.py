"""Request and response schemas for the conversational session endpoints."""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.estimation import EstimationResult
from app.sessions import ProjectMetadata


class SessionCreateResponse(BaseModel):
    """Returned by POST /sessions."""

    session_id: str


class ConversationEstimateResponse(BaseModel):
    """Returned by POST /sessions/{session_id}/estimate.

    Extends the transactional EstimationResponse with:
    - ``project_metadata``: the distilled facts accumulated so far (for the UI panel).
    - ``turn``: the current turn number within the session.
    """

    result: EstimationResult
    prompt_version: str
    cached: bool = False
    project_metadata: ProjectMetadata
    turn: int
