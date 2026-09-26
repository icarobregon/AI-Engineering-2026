"""Logfire wiring for the graph.

Configured once at startup and deliberately harmless: without ``LOGFIRE_TOKEN``
the spans still open and close, they just are not exported, so the service runs
the same on a laptop with no account as it does in a traced environment.

What is instrumented and why: FastAPI gives the request each run hangs off,
asyncpg covers both the retrieval queries and the checkpoint writes, and httpx
catches the LLM calls (the OpenAI SDK speaks httpx underneath).
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


def configure_observability(app=None, *, service_name: str = "ai-service") -> bool:
    """Configure Logfire. Returns whether traces will actually be exported."""
    import logfire

    from app.config import get_settings

    settings = get_settings()
    token = getattr(settings, "LOGFIRE_TOKEN", None)
    logfire.configure(
        service_name=service_name,
        token=token,
        # Without a token there is nothing to send: staying local keeps startup
        # from stalling on a network call that can never succeed.
        send_to_logfire=bool(token),
        console=False,
    )
    for instrument, label in (
        (lambda: logfire.instrument_asyncpg(), "asyncpg"),
        (lambda: logfire.instrument_httpx(), "httpx"),
    ):
        try:
            instrument()
        except Exception as exc:  # noqa: BLE001 - observability must never break the service
            log.warning("logfire_instrument_failed", target=label, error=str(exc)[:200])
    if app is not None:
        try:
            logfire.instrument_fastapi(app)
        except Exception as exc:  # noqa: BLE001
            log.warning("logfire_instrument_failed", target="fastapi", error=str(exc)[:200])

    log.info("observability_configured", exporting=bool(token))
    return bool(token)
