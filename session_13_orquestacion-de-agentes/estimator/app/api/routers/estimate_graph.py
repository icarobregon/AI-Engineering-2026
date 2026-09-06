"""``POST /v1/estimate/graph`` — transcript → estimate, via the graph (S13).

Thin transport, like every other router here: it resolves the thread id, invokes
the compiled graph and maps the state it gets back onto the same response shape
the business backend already consumes. No orchestration lives in this file — if
it did, the graph would not be the thing that owns the flow.
"""

from __future__ import annotations

import uuid

import logfire
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.config import get_settings
from app.domain.schemas.graph_estimation import GraphEstimateRequest, GraphEstimateResponse

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate", tags=["estimate"])


@router.post(
    "/graph",
    response_model=GraphEstimateResponse,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def estimate_via_graph(
    request: Request, payload: GraphEstimateRequest
) -> GraphEstimateResponse:
    """Run the estimation graph over one transcript."""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        # The graph is built in the lifespan; None means its checkpointer could
        # not be opened. Saying so is better than quietly running unpersisted.
        raise HTTPException(status_code=503, detail="The estimation graph is not available.")

    estimation_id = payload.estimation_id or str(uuid.uuid4())
    settings = get_settings()
    config = {
        "configurable": {"thread_id": estimation_id},
        "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
    }

    try:
        # A thread that already finished is ANSWERED, not re-run. Re-invoking it
        # opens a fresh superstep over the persisted channels, and the
        # accumulators (budget_matches, errors) append the second run's writes to
        # the first's: the evidence doubles, and a retry whose retrieval failed
        # still finds the previous run's matches and certifies components as
        # grounded on references it never retrieved. Sending an estimation_id
        # twice is a documented client flow, so this is the retry path, not an
        # exotic one.
        snapshot = await graph.aget_state(config)
        if snapshot.values and not snapshot.next:
            log.info("graph_estimate_replayed", estimation_id=estimation_id)
            result = snapshot.values
        else:
            # Only new input goes in. Passing accumulator fields would make their
            # reducers concatenate them with what is already persisted.
            with logfire.span("estimation graph run", thread_id=estimation_id):
                result = await graph.ainvoke({"transcript": payload.transcript}, config)
    except Exception as exc:  # noqa: BLE001 - transport boundary
        log.error(
            "graph_estimate_failed",
            estimation_id=estimation_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to produce an estimate.") from exc

    return GraphEstimateResponse(
        estimate=result.get("estimate"),
        status=result.get("status") or "needs_review",
        estimation_id=estimation_id,
        errors=result.get("errors") or [],
    )
