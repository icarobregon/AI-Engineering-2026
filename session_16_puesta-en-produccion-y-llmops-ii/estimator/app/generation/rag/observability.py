"""Per-stage structured logging for the RAG pipeline (Sessions 9 and 11).

``log_stage`` wraps each pipeline step so every stage emits a consistent
``stage.started`` / ``stage.completed`` (with ``duration_ms``) / ``stage.failed``
trio, all correlated by a shared ``request_id``. This makes a single request's
journey through reformulation → retrieval → augmentation → generation trivially
greppable in the JSON logs.

``log_citation_report`` (S11) emits the per-line grounding outcome under the same
``request_id``. It is a separate call rather than extra ``log_stage`` context
because the counters only exist once the stage body has run, while ``log_stage``
evaluates its context before yielding.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator

import structlog

from app.generation.rag.schemas import CitationReport

log = structlog.get_logger()


@contextmanager
def log_stage(stage: str, request_id: str, **context: Any) -> Iterator[None]:
    """Log the lifecycle of one pipeline ``stage`` bound to ``request_id``.

    Parameters
    ----------
    stage:
        Stage name, e.g. ``"reformulation"`` or ``"generation"``.
    request_id:
        UUID correlating every stage of the same request.
    **context:
        Extra structured fields attached to all three events.

    Yields
    ------
    None
        The body runs inside the ``try``; any exception is logged as
        ``stage.failed`` (with ``duration_ms`` and the error type) and re-raised.
    """
    log.info("stage.started", stage=stage, request_id=request_id, **context)
    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        log.error(
            "stage.failed",
            stage=stage,
            request_id=request_id,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
            **context,
        )
        raise
    duration_ms = int((time.perf_counter() - t0) * 1000)
    log.info(
        "stage.completed",
        stage=stage,
        request_id=request_id,
        duration_ms=duration_ms,
        **context,
    )


def log_citation_report(
    report: CitationReport,
    request_id: str,
    *,
    retried: bool = False,
) -> None:
    """Emit the per-line citation outcome for one estimate, bound to ``request_id``.

    A dangling citation is a quality failure, not a cosmetic detail: it is logged
    at WARNING with the offending ids so it surfaces in the same grep as the rest
    of the request. A clean report is logged at INFO so the counters are always
    available for the evaluation harness, not only when something breaks.

    Parameters
    ----------
    report:
        The verdict from :func:`validation.verify_citations`, describing what the
        model produced (before any policy is applied).
    request_id:
        UUID correlating this with the request's other stages.
    retried:
        Whether this report is the one measured after the corrective retry.
    """
    # Both signals matter: a fabricated id cited only in the estimate's top-level
    # `sources` raises no per-line verdict, but it is still a fabricated id.
    emit = log.warning if (report.dangling or report.dangling_source_ids) else log.info
    emit(
        "citation_report",
        request_id=request_id,
        retried=retried,
        lines=len(report.lines),
        grounded=report.grounded,
        dangling=report.dangling,
        insufficient=report.insufficient,
        dangling_source_ids=report.dangling_source_ids,
    )
