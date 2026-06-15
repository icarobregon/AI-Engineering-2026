"""Router for project estimation endpoints."""

from fastapi import APIRouter, HTTPException, Query
from jinja2 import TemplateNotFound

from app.logging import get_logger
from app.schemas.estimation import EstimationRequest, EstimationResponse
from app.services.llm_service import generate_estimation

router = APIRouter()
log = get_logger(__name__)


@router.post("/estimate", response_model=EstimationResponse)
def estimate(
    request: EstimationRequest,
    prompt_version: str = Query("v1", pattern=r"^v[0-9]+$"),
) -> EstimationResponse:
    """Generate a project estimation from a typed EstimationRequest."""
    log.info(
        "estimate_request_received",
        project_type=request.project_type.value,
        detail_level=request.detail_level.value,
        output_format=request.output_format.value,
        description_length=len(request.description),
        prompt_version=prompt_version,
    )

    try:
        result = generate_estimation(request, prompt_version=prompt_version)
        log.info("estimate_request_completed", prompt_version=result["prompt_version"])
        return EstimationResponse(**result)
    except TemplateNotFound:
        log.warning("estimate_unknown_prompt_version", prompt_version=prompt_version)
        raise HTTPException(
            status_code=404,
            detail=f"Unknown prompt_version: {prompt_version!r}",
        )
    except Exception as e:
        log.error("estimate_request_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
