"""Token and cost accumulation for one request (Session 16).

Until now the service could tell you how long a request took but not what it
cost. The price of every individual call was already computed in
``LLMWrapper._usage_from`` — and then logged and forgotten. Nothing added them
up, so "what does an estimate cost" was a question you answered by reading a
provider invoice at the end of the month.

WHY A MUTABLE OBJECT AND NOT A COUNTER. The accumulator lives in a
:mod:`contextvars` variable, the same technique ``app/main.py`` already uses to
bind ``request_id``, so nothing has to be threaded through the call stack. But
most of the estimation pipeline runs its blocking work through
``asyncio.to_thread`` (see ``app/domain/graph/llm.py`` and half of
``app/generation/rag/``), and ``to_thread`` executes the function in a COPY of
the context: rebinding a ContextVar inside that thread would be invisible to the
caller. Mutating the object the variable points at is visible, because both
contexts hold the same reference. Every ``+=`` below is in-place on purpose, and
that is the whole design.

WHY "NO USAGE" IS NOT "ZERO". ``_usage_from`` returns nothing when the provider
answers without a usage block, and a request whose usage never arrived is not a
free request. Those calls are counted apart, in ``calls_without_usage``, so the
dashboard can say "unknown" instead of believing a zero. The same rule the
wrapper already states about prices: a cost of zero is worse than no cost at
all, because a number gets believed.

Outside a request — CLI scripts, the eval harness, the test suite — there is no
active accumulator and :func:`record_llm_call` does nothing. Instrumentation
must never be the reason something fails.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from typing import Any

import structlog

__all__ = [
    "RequestMetrics",
    "emit_request_metrics",
    "begin_request",
    "current_metrics",
    "end_request",
    "record_failed_call",
    "record_llm_call",
]


@dataclass
class RequestMetrics:
    """Running totals for one request, or for one detached graph run.

    ``llm_calls`` counts round trips, not attempts: when Instructor re-prompts on
    a validation error it is the same logical call and the wrapper records it
    once, with the usage of the attempt that succeeded. The attempts that were
    paid for and thrown away arrive through :meth:`add_wasted`, which is the only
    way a six-round failure stops reporting zero spend.
    """

    llm_calls: int = 0
    failed_calls: int = 0
    calls_without_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, *, tokens_in: int | None, tokens_out: int | None, cost_usd: float | None) -> None:
        self.llm_calls += 1
        if tokens_in is None and tokens_out is None:
            self.calls_without_usage += 1
            return
        self.prompt_tokens += max(0, int(tokens_in or 0))
        self.completion_tokens += max(0, int(tokens_out or 0))
        self.cost_usd += float(cost_usd or 0.0)

    def add_wasted(self, *, tokens_in: int | None, tokens_out: int | None, cost_usd: float) -> None:
        """Tokens spent on a call that then failed. They are paid for all the same."""
        self.failed_calls += 1
        self.prompt_tokens += max(0, int(tokens_in or 0))
        self.completion_tokens += max(0, int(tokens_out or 0))
        self.cost_usd += float(cost_usd or 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "llm_calls": self.llm_calls,
            "failed_llm_calls": self.failed_calls,
            "calls_without_usage": self.calls_without_usage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            # Ocho decimales, y no seis: la llamada de embeddings de una
            # recuperacion son ocho tokens, o sea 0,00000016 $, que a seis
            # decimales se imprime como 0.0 — el cero que un panel se cree, que
            # es contra lo que lleva avisando la tabla de precios desde la S15.
            "estimated_cost": round(self.cost_usd, 8),
        }


_current: contextvars.ContextVar[RequestMetrics | None] = contextvars.ContextVar(
    "request_metrics", default=None
)


def begin_request() -> contextvars.Token:
    """Start a fresh accumulator. Returns the token :func:`end_request` needs."""
    return _current.set(RequestMetrics())


def end_request(token: contextvars.Token) -> RequestMetrics:
    """Close the accumulator opened by ``token`` and return its totals."""
    metrics = _current.get() or RequestMetrics()
    _current.reset(token)
    return metrics


def current_metrics() -> RequestMetrics | None:
    """The accumulator for the request in flight, or ``None`` outside one."""
    return _current.get()


def record_llm_call(
    *, tokens_in: int | None, tokens_out: int | None, cost_usd: float | None
) -> None:
    """Add one completed LLM call to the request in flight. No-op outside one."""
    metrics = _current.get()
    if metrics is not None:
        metrics.add(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)


def record_failed_call(
    *, tokens_in: int | None, tokens_out: int | None, cost_usd: float = 0.0
) -> None:
    """Add the tokens burned by a call that failed. No-op outside a request."""
    metrics = _current.get()
    if metrics is not None:
        metrics.add_wasted(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost_usd)


# Ni las sondas ni el propio panel entran en el libro de cuentas. Compose llama
# a /health cada quince segundos: contarla haria que «la latencia p95 del
# servicio» fuese en realidad la p95 de un latido, y que la mediana del coste
# por peticion fuese cero. Y el resumen de metricas se mide a si mismo: una
# pantalla abierta con refresco periodico acaba siendo la ruta mas transitada
# del sistema y hunde la media de latencia de todo lo demas. Observar no puede
# cambiar lo observado.
UNMETERED_ROUTES = frozenset(
    {"/health", "/docs", "/redoc", "/openapi.json", "/v1/metrics/summary"}
)

_request_log = structlog.get_logger("ai-service.requests")


def emit_request_metrics(
    *,
    request_id: str,
    route: str,
    method: str,
    status: int | str,
    started: float,
    token: contextvars.Token,
) -> dict[str, Any] | None:
    """Cierra el acumulador y emite EL evento por peticion.

    Uno solo y con todo dentro. Sin el hay que correlacionar N eventos de llamada
    al modelo por su ``request_id`` para saber lo que costo una estimacion, que
    es justo el trabajo que un panel no puede hacer en vivo.

    Lo llaman dos sitios, y esa es la razon de que viva aqui y no en el
    middleware: las ejecuciones del grafo que arrancan por ``/graph/start``
    corren en una ``BackgroundTask``, es decir DESPUES de que la respuesta se
    haya enviado y el middleware haya cerrado su contexto. Su gasto no puede
    llegar al evento de la peticion que las lanzo, asi que abren el suyo.
    """
    metrics = end_request(token)
    if route in UNMETERED_ROUTES:
        return None
    payload = {
        "request_id": request_id,
        "route": route,
        "method": method,
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        **metrics.as_dict(),
    }
    _request_log.info("request_completed", **payload)
    # Se DEVUELVE en vez de guardarse aqui: este paquete no toca disco ni base
    # de datos. Quien lo llama —el middleware y la ejecucion desacoplada del
    # grafo— decide que hacer con ello, y la capa de persistencia se queda
    # donde vive el resto de la persistencia.
    return payload
