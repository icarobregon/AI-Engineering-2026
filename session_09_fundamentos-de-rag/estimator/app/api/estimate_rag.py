"""HTTP layer for the RAG estimation surface (Session 9).

``POST /v1/estimate/from-transcript`` is the endpoint the business backend
actually calls: transcript in, cited estimate out. Its contract is deliberately
minimal — the transcript and an optional idempotency key — so no caller can
change retrieval parameters and get a different number for the same meeting.

A ``low_confidence`` answer is a **200**, not an error: "the corpus has nothing
comparable, a human must look at this" is a legitimate, useful outcome of the
product, and the response body carries the retrieval trace that explains it.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.security import require_estimate_key
from app.config import get_settings
from app.dependencies import get_estimation_service
from app.domain.estimation_service import EstimationService, RagFlowUnavailable
from app.domain.schemas.rag_estimate import EstimateRequest, EstimateResponse
from app.rate_limit import limiter

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate", tags=["estimate"])


@router.post("/from-transcript", response_model=EstimateResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_ESTIMATE)
async def estimate_from_transcript(
    request: Request,  # required by slowapi's decorator
    payload: EstimateRequest,
    response: Response,
    service: EstimationService = Depends(get_estimation_service),
    _key: str = Depends(require_estimate_key),
) -> EstimateResponse:
    """Run the full RAG flow over a meeting transcript."""
    try:
        result = await service.estimate_from_transcript(
            payload.transcript, idempotency_key=payload.idempotency_key
        )
    except RagFlowUnavailable as exc:
        log.error("estimate_from_transcript_unavailable", error=str(exc)[:200])
        raise HTTPException(
            status_code=503, detail="Estimation flow is not configured."
        ) from exc
    except Exception as exc:  # noqa: BLE001 — any stage failure is a 502.
        log.error(
            "estimate_from_transcript_failed",
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to produce an estimate.") from exc

    # Correlation id back to the caller, so a support ticket can quote it and
    # the whole five-stage trace comes back from one grep.
    response.headers["X-Request-ID"] = result.request_id
    return result
