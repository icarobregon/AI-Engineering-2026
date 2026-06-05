"""Router for project estimation endpoints."""

import json

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.logging import get_logger
from app.schemas.estimation import EstimationRequest, EstimationResponse
from app.services.llm_service import generate_estimation, stream_estimation

router = APIRouter()
log = get_logger(__name__)


@router.post("/estimate", response_model=EstimationResponse)
def estimate(request: EstimationRequest) -> EstimationResponse:
    """Generate a project cost and time estimation from a meeting transcription."""
    log.info(
        "estimate_request_received",
        transcription_length=len(request.transcription),
    )

    try:
        result = generate_estimation(request.transcription)
        log.info(
            "estimate_request_completed",
            estimation=result["estimation"]
        )
        return EstimationResponse(**result)
    except Exception as e:
        log.error("estimate_request_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/estimate/stream")
def estimate_stream(request: EstimationRequest) -> EventSourceResponse:
    """Stream a project estimation via Server-Sent Events.

    Emits three event kinds: `delta` (text chunks), `meta` (model + token usage
    once at the end), and `error` (if the LLM fails mid-stream).
    """
    log.info(
        "estimate_stream_request_received",
        transcription_length=len(request.transcription),
    )

    def event_generator():
        for event in stream_estimation(request.transcription):
            etype = event.pop("type")
            if etype == "delta":
                payload = event["text"]
            elif etype == "error":
                payload = event["message"]
            else:
                payload = json.dumps(event)
            yield {"event": etype, "data": payload}

    return EventSourceResponse(event_generator())
