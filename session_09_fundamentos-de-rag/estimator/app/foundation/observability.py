"""Per-stage instrumentation for multi-stage flows.

A four-stage RAG request that answers badly is not debuggable from a single log
line at the end. Each stage emits ``started``/``completed`` with its own
``duration_ms`` and a ``request_id`` shared by all of them, so one grep
reconstructs the whole request: which stage was slow, which one raised, what
the retriever was asked for and what the generator was handed.

The exception path logs and re-raises. Swallowing here would turn a stage
failure into a silently degraded answer, which is precisely the failure mode
this module exists to make visible.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager

import structlog

logger = structlog.get_logger()


def new_request_id() -> str:
    """Correlation id propagated to the client as ``X-Request-ID``."""
    return uuid.uuid4().hex


@contextmanager
def log_stage(stage: str, request_id: str, **context):
    """Time one stage and emit its start/end (or failure) events."""
    start = time.perf_counter()
    log = logger.bind(stage=stage, request_id=request_id, **context)
    log.info("stage.started")
    try:
        yield log
        duration_ms = (time.perf_counter() - start) * 1000
        log.info("stage.completed", duration_ms=round(duration_ms, 2))
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        log.exception("stage.failed", duration_ms=round(duration_ms, 2), error=str(exc))
        raise
