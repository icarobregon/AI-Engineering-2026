"""The trace the exercise actually asks for: ONE trace, one span per node.

Nivel 2's acceptance criterion is a complete trace of a run with a span per
node. Node spans alone do not give that: without a parent, each one opens its
own root span and the run arrives as five unrelated traces. This pins both the
nesting and the presence of every node.
"""

from __future__ import annotations

import logfire
import pytest
from langgraph.checkpoint.memory import MemorySaver
from logfire.testing import TestExporter

from app.domain.graph.build import build_graph
from app.domain.graph.nodes import build_nodes
from app.domain.graph.observability import configure_observability

TRANSCRIPT = "Reunión: backend de pedidos y app de repartidores."


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


async def test_one_trace_carries_a_span_for_every_node(exporter, fake_llm, fake_backend):
    nodes = build_nodes(
        llm=fake_llm, search_backend=fake_backend, fast_model="fast", estimate_model="strong"
    )
    graph = build_graph(nodes, checkpointer=MemorySaver())

    with logfire.span("estimation graph run", thread_id="trace-1"):
        await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "trace-1"}})

    spans = exporter.exported_spans_as_dict()
    names = [span["name"] for span in spans]
    for node in (
        "extract_requirements",
        "classify_components",
        "search_budgets",
        "generate_estimate",
        "validate_and_consolidate",
    ):
        assert f"node: {node}" in names, node

    # All of them in ONE trace, hanging off the run span.
    trace_ids = {span["context"]["trace_id"] for span in spans}
    assert len(trace_ids) == 1
    parents = {span["parent"]["span_id"] for span in spans if span["name"].startswith("node: ")}
    run_span = next(s for s in spans if s["name"] == "estimation graph run")
    assert parents == {run_span["context"]["span_id"]}


async def test_node_spans_carry_the_cost_of_the_call(exporter, fake_llm, fake_backend):
    nodes = build_nodes(
        llm=fake_llm, search_backend=fake_backend, fast_model="fast", estimate_model="strong"
    )
    graph = build_graph(nodes, checkpointer=MemorySaver())

    await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "trace-2"}})

    spans = {s["name"]: s for s in exporter.exported_spans_as_dict()}
    attributes = spans["node: generate_estimate"]["attributes"]
    # "What does an estimate cost" has to be a query over the trace, which means
    # the number has to be on the span in the first place.
    assert attributes["llm_cost_usd"] == pytest.approx(0.002)
    assert attributes["model"] == "strong"


def test_observability_is_a_no_op_without_a_token(monkeypatch):
    from app.domain.graph import observability

    monkeypatch.setattr(
        observability,
        "get_settings",
        lambda: type("S", (), {"LOGFIRE_TOKEN": None})(),
        raising=False,
    )
    # No token is a supported mode, not a degraded one: the service must run.
    assert configure_observability() is False
