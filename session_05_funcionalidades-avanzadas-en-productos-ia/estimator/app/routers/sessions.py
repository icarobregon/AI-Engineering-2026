"""Conversational session endpoints.

POST /sessions          → create a new session, return session_id
POST /sessions/{id}/estimate → run one conversational estimation turn

Error mapping mirrors the transactional router:
- InputGuardrailViolation → HTTP 400 with {reason, message}
- Session not found       → HTTP 404
- Everything else         → HTTP 502
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.attachments import ExtractionResult, extract_text
from app.dependencies import get_conversation_service, get_session_store
from app.guardrails.input import InputGuardrailViolation
from app.schemas.conversation import ConversationEstimateResponse, SessionCreateResponse
from app.schemas.estimation import DetailLevel, OutputFormat, ProjectType
from app.services.conversation import ConversationService
from app.sessions import SessionStore

log = structlog.get_logger()

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionCreateResponse, status_code=201)
def create_session(store: SessionStore = Depends(get_session_store)) -> SessionCreateResponse:
    """Create a new conversation session and return its ID."""
    session = store.create()
    log.info("session_created", session_id=session.session_id)
    return SessionCreateResponse(session_id=session.session_id)


@router.post("/{session_id}/estimate", response_model=ConversationEstimateResponse)
async def conversation_estimate(
    session_id: str,
    description: str = Form(..., min_length=20, max_length=80000),
    project_type: ProjectType = Form(...),
    detail_level: DetailLevel = Form(...),
    output_format: OutputFormat = Form(...),
    files: list[UploadFile] = File(default=[]),
    store: SessionStore = Depends(get_session_store),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationEstimateResponse:
    """Run one conversational estimation turn within an existing session.

    Accepts ``multipart/form-data`` with:
    - description: the user's transcript or free-text description.
    - project_type, detail_level, output_format: same enums as the transactional endpoint.
    - files (optional): one or more PDF or DOCX attachments.
    """
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    # Extract text from uploaded attachments.
    attachments: list[ExtractionResult] = []
    for upload in files:
        if upload.filename and upload.size and upload.size > 0:
            content = await upload.read()
            attachments.append(extract_text(upload.filename, content))

    log.info(
        "conversation_estimate_request",
        session_id=session_id,
        turn=session.history.turn_count + 1,
        project_type=project_type.value,
        attachments=len(attachments),
        description_chars=len(description),
    )

    from app.schemas.estimation import EstimationRequest

    request = EstimationRequest(
        description=description,
        project_type=project_type,
        detail_level=detail_level,
        output_format=output_format,
    )

    try:
        return service.estimate(session, request, attachments)
    except InputGuardrailViolation as exc:
        log.info(
            "conversation_blocked_by_input_guardrail",
            session_id=session_id,
            reason=exc.reason,
            message=exc.message,
        )
        raise HTTPException(
            status_code=400, detail={"reason": exc.reason, "message": exc.message}
        ) from exc
    except Exception as exc:
        log.error(
            "conversation_estimate_error",
            session_id=session_id,
            error=str(exc)[:400],
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Upstream LLM call failed") from exc
