"""Per-request observability primitives (Session 16).

Session 13 gave the service spans and Session 15 gave it a ``request_id``; what
it never had was the answer to "what did THIS request cost". Token counts and
prices existed inside each LLM call, were logged, and were dropped on the floor.
This package is the accumulator that adds them up and the one event that reports
them.

It deliberately holds no I/O and no DB: the middleware decides what to do with
the totals. Instrumentation that can fail the thing it observes is worse than no
instrumentation.
"""

from app.foundation.observability.metrics import (
    RequestMetrics,
    begin_request,
    current_metrics,
    emit_request_metrics,
    end_request,
    record_failed_call,
    record_llm_call,
)

__all__ = [
    "RequestMetrics",
    "begin_request",
    "current_metrics",
    "emit_request_metrics",
    "end_request",
    "record_failed_call",
    "record_llm_call",
]
