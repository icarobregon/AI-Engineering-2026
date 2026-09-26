"""The per-request cost ledger (Session 16).

Three things are pinned here, and each one was a decision rather than an
accident: that the accumulator survives the thread hop the pipeline makes on
every LLM call, that the liveness probe stays out of the ledger, and that a
request which failed is still accounted for.

Nothing here calls a model. The accumulator is fed by hand, which is the point:
the arithmetic of what a request cost must be testable without buying tokens.
"""

from __future__ import annotations

import asyncio

import structlog

from app.foundation.observability import (
    begin_request,
    current_metrics,
    end_request,
    record_failed_call,
    record_llm_call,
)
from app.main import request_id_middleware


def test_the_accumulator_survives_the_thread_hop() -> None:
    """The reason it is a mutable object and not a counter.

    Every structured call in the graph and half of the RAG pipeline runs through
    ``asyncio.to_thread``, which executes in a COPY of the context. A ContextVar
    rebound inside that copy is invisible to the caller, so a design that
    reassigned the variable would silently lose the cost of exactly the calls
    that cost money. Mutating the object both contexts point at does not.
    """

    async def scenario() -> dict:
        token = begin_request()

        def blocking_work() -> None:
            record_llm_call(tokens_in=1000, tokens_out=200, cost_usd=0.01)

        await asyncio.to_thread(blocking_work)
        await asyncio.to_thread(blocking_work)
        return end_request(token).as_dict()

    totals = asyncio.run(scenario())
    assert totals["llm_calls"] == 2
    assert totals["prompt_tokens"] == 2000
    assert totals["estimated_cost"] == 0.02


def test_a_call_without_usage_is_unknown_and_not_free() -> None:
    """A provider that answers without a usage block did not work for free.

    Folding it in as zero would put a number in the dashboard, and a number gets
    believed. It is counted apart so the panel can say "unknown".
    """
    token = begin_request()
    record_llm_call(tokens_in=None, tokens_out=None, cost_usd=None)
    record_llm_call(tokens_in=100, tokens_out=50, cost_usd=0.002)
    totals = end_request(token).as_dict()
    assert totals["llm_calls"] == 2
    assert totals["calls_without_usage"] == 1
    assert totals["total_tokens"] == 150
    assert totals["estimated_cost"] == 0.002


def test_tokens_burned_by_a_failed_call_are_still_spent() -> None:
    """Instructor re-prompting six times and then raising has cost six calls.

    Counting only successes makes the most expensive request of the day the one
    that reports nothing.
    """
    token = begin_request()
    record_failed_call(tokens_in=4000, tokens_out=600, cost_usd=0.05)
    totals = end_request(token).as_dict()
    assert totals["llm_calls"] == 0
    assert totals["failed_llm_calls"] == 1
    assert totals["total_tokens"] == 4600
    assert totals["estimated_cost"] == 0.05


def test_outside_a_request_recording_is_a_no_op() -> None:
    """Scripts, the eval harness and the test suite all call the wrapper.

    Instrumentation must never be the reason something fails, so with no
    accumulator open there is nothing to add to and nothing to raise about.
    """
    assert current_metrics() is None
    record_llm_call(tokens_in=10, tokens_out=10, cost_usd=0.1)  # no raise
    assert current_metrics() is None


# --------------------------------------------------------------------------- #
# The middleware
# --------------------------------------------------------------------------- #


class _FakeURL:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRequest:
    """The three attributes the middleware touches, and nothing else."""

    def __init__(self, path: str, method: str = "POST") -> None:
        self.url = _FakeURL(path)
        self.method = method
        self.headers: dict[str, str] = {}
        self.scope: dict = {}

        class _State:
            pass

        self.state = _State()


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}


def _events_for(path: str, *, call_next) -> list[dict]:
    with structlog.testing.capture_logs() as logs:
        try:
            asyncio.run(request_id_middleware(_FakeRequest(path), call_next))
        except RuntimeError:
            pass  # the deliberate failure of the 500 case
    return [entry for entry in logs if entry.get("event") == "request_completed"]


def test_a_request_emits_one_event_with_everything_in_it() -> None:
    """One event per request, not N events to correlate afterwards.

    The per-call logs already existed; what did not exist was a line a dashboard
    can read without joining anything.
    """

    async def call_next(request):
        record_llm_call(tokens_in=1200, tokens_out=300, cost_usd=0.004)
        return _FakeResponse(200)

    events = _events_for("/v1/estimate/from-transcript", call_next=call_next)
    assert len(events) == 1
    event = events[0]
    for field in (
        "request_id",
        "route",
        "status",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "estimated_cost",
    ):
        assert field in event, field
    assert event["prompt_tokens"] == 1200
    assert event["estimated_cost"] == 0.004
    assert event["status"] == 200


def test_the_liveness_probe_stays_out_of_the_ledger() -> None:
    """Compose polls /health every 15 s.

    Counted, it would be most of the rows: the p95 latency of the service would
    really be the p95 of a heartbeat, and the median cost per request would be
    zero by construction.
    """

    async def call_next(request):
        return _FakeResponse(200)

    assert _events_for("/health", call_next=call_next) == []


def test_a_request_that_blew_up_is_still_accounted_for() -> None:
    """``BaseHTTPMiddleware`` does not catch: the exception goes past it.

    Reading the status off the response object alone would leave out exactly the
    requests that failed hardest — and the tokens they had already spent.
    """

    async def call_next(request):
        record_llm_call(tokens_in=900, tokens_out=100, cost_usd=0.003)
        raise RuntimeError("boom")

    events = _events_for("/v1/estimate/from-transcript", call_next=call_next)
    assert len(events) == 1
    assert events[0]["status"] == 500
    assert events[0]["prompt_tokens"] == 900
