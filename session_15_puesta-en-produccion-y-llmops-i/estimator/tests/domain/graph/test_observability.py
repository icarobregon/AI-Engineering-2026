"""The trace the exercise actually asks for: ONE trace, every decision visible.

The first acceptance criterion is that each routing decision appears in the
trace. Spans alone do not give that: without a parent, each one opens its own
root span and the run arrives as a handful of unrelated traces. This pins the
nesting, the presence of every agent, and the routing decision on the
supervisor's own span — which is exactly what gets lost when the routing is
delegated to an abstraction.
"""

from __future__ import annotations

import logfire
import pytest
from logfire.testing import TestExporter

from app.domain.graph.observability import configure_observability

from .conftest import build_test_graph, config, start


@pytest.fixture
def exporter():
    exporter = TestExporter()
    logfire.configure(
        send_to_logfire=False,
        console=False,
        additional_span_processors=[
            __import__(
                "opentelemetry.sdk.trace.export", fromlist=["SimpleSpanProcessor"]
            ).SimpleSpanProcessor(exporter)
        ],
    )
    yield exporter
    exporter.clear()


async def test_one_trace_carries_a_span_for_every_agent(exporter, fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend, fast_model="fast", estimate_model="strong")

    with logfire.span("estimation graph run", thread_id="trace-1"):
        await graph.ainvoke(start("trace-1"), config("trace-1"))

    spans = exporter.exported_spans_as_dict()
    names = [span["name"] for span in spans]
    for agent in (
        "requirements_extractor",
        "budget_searcher",
        "estimate_generator",
        "coherence_validator",
        "human_review_gate",
        "finalize",
    ):
        assert f"agent.{agent}" in names, agent
    assert "supervisor.route" in names

    # All of them in ONE trace, hanging off the run span.
    trace_ids = {span["context"]["trace_id"] for span in spans}
    assert len(trace_ids) == 1
    graph_spans = [span for span in spans if span["name"].startswith(("agent.", "supervisor."))]
    parents = {span["parent"]["span_id"] for span in graph_spans}
    run_span = next(s for s in spans if s["name"] == "estimation graph run")
    assert parents == {run_span["context"]["span_id"]}


async def test_every_routing_decision_is_on_the_supervisors_span(exporter, fake_llm, fake_backend):
    """This is the criterion. Delegate the routing to a prebuilt supervisor and
    this is precisely what stops being visible."""
    graph = build_test_graph(fake_llm, fake_backend)

    await graph.ainvoke(start("trace-2"), config("trace-2"))

    routed = [
        span["attributes"]
        for span in exporter.exported_spans_as_dict()
        if span["name"] == "supervisor.route" and "next_agent" in span["attributes"]
    ]
    assert [a["next_agent"] for a in routed][:4] == [
        "requirements_extractor",
        "budget_searcher",
        "estimate_generator",
        "coherence_validator",
    ]
    assert all(a["reason"] for a in routed)


async def test_agent_spans_carry_the_cost_of_the_call(exporter, fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend, fast_model="fast", estimate_model="strong")

    await graph.ainvoke(start("trace-3"), config("trace-3"))

    spans = {s["name"]: s for s in exporter.exported_spans_as_dict()}
    attributes = spans["agent.estimate_generator"]["attributes"]
    # "What does an estimate cost" has to be a query over the trace, which means
    # the number has to be on the span in the first place.
    assert attributes["llm_cost_usd"] == pytest.approx(0.002)
    assert attributes["model"] == "strong"


async def test_a_pause_is_not_reported_as_an_error(exporter, fake_llm, empty_backend):
    """``interrupt()`` works by raising, so a span wrapping it is closed by an
    exception and exported with status=ERROR. A run stopping for a human is the
    system working; it must not arrive in the dashboard looking like a failure.
    """
    graph = build_test_graph(fake_llm, empty_backend)

    await graph.ainvoke(start("trace-4"), config("trace-4"))

    spans = exporter.exported_spans_as_dict()
    statuses = {span["name"]: span.get("status", {}).get("status_code") for span in spans}
    assert "ERROR" not in statuses.values(), statuses
    # And no half-span either: on the pausing pass the gate opens nothing at all,
    # because the interrupt happens before the span does.
    assert "agent.human_review_gate" not in statuses


def test_observability_is_a_no_op_without_a_token(monkeypatch):
    """No token is a supported mode, not a degraded one: the service must run.

    The patch goes on ``app.config``, not on the observability module: the
    function imports ``get_settings`` inside its own body, so patching the name
    where it is *used* does nothing. The first version did exactly that and
    passed only while no token happened to be configured — the day a real one
    landed in .env the test read it, asserted against reality, and tried to
    export to the network from the test suite.
    """
    import app.config

    monkeypatch.setattr(
        app.config, "get_settings", lambda: type("S", (), {"LOGFIRE_TOKEN": None})()
    )

    assert configure_observability() is False
