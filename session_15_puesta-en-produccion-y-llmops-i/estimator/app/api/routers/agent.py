"""POST /v1/estimate/agent/run — el agente escrito a mano de la Sesión 12, por HTTP.

Hasta ahora sólo se ejecutaba con ``scripts/run_agent_s12.py``. Exponerlo es lo
que convierte una consola de perfiles en algo que gobierna de verdad un agente,
en lugar de un formulario que guarda ajustes que nadie lee.

**Es síncrono y puede tardar minutos**, igual que el script: el bucle encadena
varias llamadas a un modelo de razonamiento. El trabajo en segundo plano y su
sondeo viven en el cliente, que es donde ya está el patrón (la ampliación del
corpus hace exactamente lo mismo). Meterlo aquí obligaría a este servicio a
guardar estado de trabajos, que es justo lo que no le toca.

El router es fino, como los demás: valida, resuelve dependencias, llama al bucle
y mapea excepciones. Ninguna decisión del agente vive aquí.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.config import Settings, get_settings
from app.dependencies import get_async_openai_client, get_budget_search_backend
from app.generation.agentic.agent_loop import run_estimation_agent
from app.generation.agentic.agent_schemas import AgentEstimate, AgentTrace

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate/agent", tags=["agent"])

# Los mismos que acepta el script. Se validan aquí para que un valor imposible
# sea un 422 con nombre de campo y no un error del proveedor a los tres minutos.
_EFFORTS = ("minimal", "low", "medium", "high")


class AgentRunRequest(BaseModel):
    """Una ejecución del agente, con los ajustes que la consola deja elegir.

    Todo lo opcional cae al valor de ``.env`` cuando no viaja: un perfil que sólo
    cambia el modelo no tiene que repetir el resto de la configuración.
    """

    transcript: str = Field(min_length=100, max_length=50_000)
    model: str | None = Field(default=None, description="Por defecto, AGENT_MODEL.")
    reasoning_effort: str | None = Field(
        default=None, description="minimal | low | medium | high."
    )
    max_iterations: int | None = Field(
        default=None,
        ge=1,
        le=30,
        description="Techo de vueltas del bucle. El corte natural es una vuelta sin tool call.",
    )


class AgentRunResponse(BaseModel):
    estimate: AgentEstimate
    trace: AgentTrace


@router.post(
    "/run",
    response_model=AgentRunResponse,
    dependencies=[Depends(require_estimate_key)],
)
# Diez por hora y no más: cada ejecución son varias llamadas a un modelo de
# razonamiento, así que el límite protege la factura, no el CPU.
@limiter.limit("10/hour")
async def run_agent(
    request: Request,
    payload: AgentRunRequest,
    settings: Settings = Depends(get_settings),
) -> AgentRunResponse:
    client = get_async_openai_client()
    if client is None:
        raise HTTPException(
            status_code=503, detail="The agent needs OPENAI_API_KEY, which is not configured."
        )

    effort = payload.reasoning_effort or settings.AGENT_REASONING_EFFORT
    if effort not in _EFFORTS:
        raise HTTPException(
            status_code=422,
            detail=f"reasoning_effort must be one of {', '.join(_EFFORTS)}.",
        )

    model = payload.model or settings.AGENT_MODEL
    max_iterations = payload.max_iterations or settings.AGENT_MAX_ITERATIONS

    log.info(
        "agent_run_requested",
        model=model,
        reasoning_effort=effort,
        max_iterations=max_iterations,
        transcript_chars=len(payload.transcript),
    )

    try:
        estimate, trace = await run_estimation_agent(
            payload.transcript,
            client=client,
            backend=get_budget_search_backend(),
            model=model,
            reasoning_effort=effort,
            max_iterations=max_iterations,
        )
    except Exception as exc:  # noqa: BLE001 — la taxonomía del cliente sólo necesita 502
        log.error("agent_run_failed", error=str(exc)[:400], error_type=type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"The agent failed: {exc}") from exc

    log.info(
        "agent_run_completed",
        iterations=trace.iterations,
        stop_reason=trace.stop_reason,
        steps=len(trace.steps),
        total_hours=estimate.total_hours,
        components=len(estimate.components),
    )
    return AgentRunResponse(estimate=estimate, trace=trace)
