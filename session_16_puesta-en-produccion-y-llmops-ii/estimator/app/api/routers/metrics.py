"""``GET /v1/metrics/summary`` — las constantes vitales del servicio (Sesión 16).

El golden set mide la calidad CUANDO se lanza la evaluación, con entradas que
elegimos nosotros. Esto mide lo que el sistema hace el resto del tiempo, con las
entradas que manda el mundo: latencia media y p95, coste por petición y tasa de
error, sobre la ventana que se pida.

Transporte fino, como sus hermanos: la autenticación va declarada en el router,
el límite de ritmo en el decorador y cualquier fallo de la base de datos es un
503 —la misma traducción que el resto del servicio da a «la dependencia no
está»—. La aritmética vive en el repositorio, que es donde puede probarse.

Va detrás de la clave de estimación y no abierto: la ruta enseña qué se está
estimando, cada cuánto y lo que cuesta, que es información de negocio aunque no
lleve ni un dato personal dentro.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.dependencies import get_corpus_session_factory
from app.foundation.persistence.repositories.metrics import RequestMetricsRepository

log = structlog.get_logger()

router = APIRouter(
    prefix="/v1/metrics",
    tags=["metrics"],
    dependencies=[Depends(require_estimate_key)],
)


class MetricsSummaryResponse(BaseModel):
    """Las señales del panel, ya agregadas por el servicio.

    Se agregan aquí y no en el cliente por una razón práctica: la p95 de una
    ventana no se puede componer a partir de las p95 de sus trozos, así que un
    panel que reciba filas sueltas y las promedie estaría enseñando otra cosa
    con el mismo nombre.
    """

    window: str = Field(description="Ventana consultada: 1h, 24h o 7d.")
    since: str = Field(description="Instante desde el que se agrega, en ISO-8601.")
    requests: int = Field(ge=0, description="Peticiones atendidas en la ventana.")
    errors: int = Field(ge=0, description="Las que no acabaron en 2xx ni en 'completed'.")
    error_rate: float | None = Field(default=None, description="errors / requests.")
    mean_latency_ms: float | None = None
    p95_latency_ms: float | None = Field(
        default=None,
        description="La que delata a la minoría que sufre; la media la esconde.",
    )
    mean_cost_usd: float | None = Field(default=None, description="Coste medio por petición.")
    total_cost_usd: float = Field(ge=0, description="Lo gastado en la ventana.")
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    llm_calls: int = Field(ge=0)
    calls_without_usage: int = Field(
        ge=0,
        description=(
            "Llamadas cuyo proveedor no informó de tokens. No son gratis: son "
            "desconocidas, y por eso se cuentan aparte en vez de sumar cero."
        ),
    )
    by_route: list[dict[str, Any]] = Field(default_factory=list)
    series: list[dict[str, Any]] = Field(default_factory=list)
    recent: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/summary", response_model=MetricsSummaryResponse)
@limiter.limit("60/minute")
async def summary(
    request: Request,
    window: Literal["1h", "24h", "7d"] = Query(default="24h"),
    session_factory=Depends(get_corpus_session_factory),
) -> MetricsSummaryResponse:
    """Latencia, coste y errores del tráfico real en la ventana pedida."""
    try:
        async with session_factory() as session:
            resumen = await RequestMetricsRepository(session).summary(window)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de la BBDD es 503
        log.warning("metrics_unavailable", error_type=type(exc).__name__, error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Metrics store unavailable") from exc

    return MetricsSummaryResponse(**resumen.__dict__)
