"""The request ledger: writing one row per request and reading the vital signs.

Two halves with opposite priorities. The WRITE sits on the hot path and must
never be the reason a request fails, so it swallows everything and logs: a
dashboard that takes the service down with it is worse than no dashboard. The
READ answers the panel's questions in SQL — a window, a percentile, a group by
route — because that is what a table buys over a log file.

Both use the async stack (asyncpg). The sync one exists for the write-rare S06
ingestion paths; this runs on every single request, and blocking the event loop
on Postgres to record how fast the service is would be its own joke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.foundation.persistence.database import get_async_session_factory
from app.foundation.persistence.models import RequestMetricRow

log = structlog.get_logger()

Window = Literal["1h", "24h", "7d"]

_WINDOW_MINUTES: dict[str, int] = {"1h": 60, "24h": 60 * 24, "7d": 60 * 24 * 7}
# Un punto de la serie por hora en las ventanas largas y uno por minuto en la
# corta: una ventana de una hora repartida en cubos de una hora es un solo
# punto, o sea una raya.
_BUCKET: dict[str, str] = {"1h": "minute", "24h": "hour", "7d": "day"}

# Exito es un 2xx y tambien el 'completed' de una ejecucion en segundo plano,
# que no tiene codigo HTTP que devolver.
_SUCCESS_SQL = "(status LIKE '2%' OR status = 'completed')"


@dataclass(frozen=True)
class MetricsSummary:
    """Lo que el panel enseña, ya agregado. Ningun tipo de SQLAlchemy sale de aqui."""

    window: str
    since: str
    requests: int
    errors: int
    error_rate: float | None
    mean_latency_ms: float | None
    p95_latency_ms: float | None
    mean_cost_usd: float | None
    total_cost_usd: float
    prompt_tokens: int
    completion_tokens: int
    llm_calls: int
    calls_without_usage: int
    by_route: list[dict[str, Any]] = field(default_factory=list)
    series: list[dict[str, Any]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)


async def persist_request_metrics(payload: dict[str, Any]) -> None:
    """Escribe la fila de una peticion. Nunca levanta.

    Se llama desde el ``finally`` del middleware y desde el de la ejecucion
    desacoplada del grafo, es decir en el camino de una peticion que ya ha
    terminado o que esta a punto de contestar. Un fallo aqui —Postgres caido,
    un pool agotado— no puede convertirse en un 500: la observabilidad no puede
    ser la causa de la caida que observa. Lo que se pierde es una fila, y queda
    dicho en el log.
    """
    try:
        async with get_async_session_factory()() as session:
            session.add(
                RequestMetricRow(
                    request_id=str(payload.get("request_id", ""))[:64],
                    route=str(payload.get("route", ""))[:255],
                    method=str(payload.get("method", ""))[:16],
                    status=str(payload.get("status", ""))[:16],
                    latency_ms=float(payload.get("latency_ms") or 0.0),
                    llm_calls=int(payload.get("llm_calls") or 0),
                    failed_llm_calls=int(payload.get("failed_llm_calls") or 0),
                    calls_without_usage=int(payload.get("calls_without_usage") or 0),
                    prompt_tokens=int(payload.get("prompt_tokens") or 0),
                    completion_tokens=int(payload.get("completion_tokens") or 0),
                    estimated_cost=float(payload.get("estimated_cost") or 0.0),
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — jamas rompe la peticion que observa
        log.warning(
            "request_metrics_not_persisted",
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )


class RequestMetricsRepository:
    """Lecturas agregadas sobre ``request_metrics``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, window: Window = "24h") -> MetricsSummary:
        minutes = _WINDOW_MINUTES.get(window, _WINDOW_MINUTES["24h"])
        since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        params = {"since": since}

        totals = (
            await self._session.execute(
                text(
                    f"""
                    SELECT count(*)                                        AS requests,
                           count(*) FILTER (WHERE NOT {_SUCCESS_SQL})      AS errors,
                           avg(latency_ms)                                 AS mean_latency_ms,
                           percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                                                                           AS p95_latency_ms,
                           avg(estimated_cost)                             AS mean_cost,
                           coalesce(sum(estimated_cost), 0)                AS total_cost,
                           coalesce(sum(prompt_tokens), 0)                 AS prompt_tokens,
                           coalesce(sum(completion_tokens), 0)             AS completion_tokens,
                           coalesce(sum(llm_calls), 0)                     AS llm_calls,
                           coalesce(sum(calls_without_usage), 0)           AS unknown_usage
                      FROM request_metrics
                     WHERE recorded_at >= :since
                    """
                ),
                params,
            )
        ).mappings().one()

        by_route = [
            dict(row)
            for row in (
                await self._session.execute(
                    text(
                        f"""
                        SELECT route,
                               count(*)                                    AS requests,
                               count(*) FILTER (WHERE NOT {_SUCCESS_SQL})  AS errors,
                               avg(latency_ms)                             AS mean_latency_ms,
                               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                                                                           AS p95_latency_ms,
                               coalesce(sum(estimated_cost), 0)            AS total_cost
                          FROM request_metrics
                         WHERE recorded_at >= :since
                         GROUP BY route
                         ORDER BY total_cost DESC, requests DESC
                        """
                    ),
                    params,
                )
            ).mappings()
        ]

        series = [
            dict(row)
            for row in (
                await self._session.execute(
                    text(
                        f"""
                        SELECT date_trunc('{_BUCKET.get(window, "hour")}', recorded_at) AS bucket,
                               count(*)                                    AS requests,
                               count(*) FILTER (WHERE NOT {_SUCCESS_SQL})  AS errors,
                               avg(latency_ms)                             AS mean_latency_ms,
                               percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)
                                                                           AS p95_latency_ms,
                               coalesce(sum(estimated_cost), 0)            AS cost
                          FROM request_metrics
                         WHERE recorded_at >= :since
                         GROUP BY bucket
                         ORDER BY bucket
                        """
                    ),
                    params,
                )
            ).mappings()
        ]

        recent = [
            dict(row)
            for row in (
                await self._session.execute(
                    text(
                        """
                        SELECT recorded_at, request_id, route, method, status, latency_ms,
                               prompt_tokens + completion_tokens AS total_tokens,
                               estimated_cost, llm_calls
                          FROM request_metrics
                         ORDER BY recorded_at DESC
                         LIMIT 20
                        """
                    )
                )
            ).mappings()
        ]

        requests = int(totals["requests"] or 0)
        errors = int(totals["errors"] or 0)
        return MetricsSummary(
            window=window,
            since=since.isoformat(),
            requests=requests,
            errors=errors,
            error_rate=(errors / requests) if requests else None,
            mean_latency_ms=_f(totals["mean_latency_ms"]),
            p95_latency_ms=_f(totals["p95_latency_ms"]),
            mean_cost_usd=_f(totals["mean_cost"], 8),
            total_cost_usd=_f(totals["total_cost"], 8) or 0.0,
            prompt_tokens=int(totals["prompt_tokens"] or 0),
            completion_tokens=int(totals["completion_tokens"] or 0),
            llm_calls=int(totals["llm_calls"] or 0),
            calls_without_usage=int(totals["unknown_usage"] or 0),
            by_route=[_clean_route(r) for r in by_route],
            series=[_clean_bucket(r) for r in series],
            recent=[_clean_recent(r) for r in recent],
        )


def _f(value: Any, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


def _clean_route(row: dict[str, Any]) -> dict[str, Any]:
    requests = int(row["requests"] or 0)
    errors = int(row["errors"] or 0)
    return {
        "route": row["route"],
        "requests": requests,
        "error_rate": (errors / requests) if requests else None,
        "mean_latency_ms": _f(row["mean_latency_ms"]),
        "p95_latency_ms": _f(row["p95_latency_ms"]),
        "total_cost_usd": _f(row["total_cost"], 8) or 0.0,
    }


def _clean_bucket(row: dict[str, Any]) -> dict[str, Any]:
    bucket: datetime = row["bucket"]
    requests = int(row["requests"] or 0)
    errors = int(row["errors"] or 0)
    return {
        "bucket": bucket.isoformat(),
        "requests": requests,
        "errors": errors,
        "error_rate": (errors / requests) if requests else None,
        "mean_latency_ms": _f(row["mean_latency_ms"]),
        "p95_latency_ms": _f(row["p95_latency_ms"]),
        "cost_usd": _f(row["cost"], 8) or 0.0,
    }


def _clean_recent(row: dict[str, Any]) -> dict[str, Any]:
    recorded_at: datetime = row["recorded_at"]
    return {
        "recorded_at": recorded_at.isoformat(),
        "request_id": row["request_id"],
        "route": row["route"],
        "method": row["method"],
        "status": row["status"],
        "latency_ms": _f(row["latency_ms"]),
        "total_tokens": int(row["total_tokens"] or 0),
        "estimated_cost": _f(row["estimated_cost"], 8) or 0.0,
        "llm_calls": int(row["llm_calls"] or 0),
    }
