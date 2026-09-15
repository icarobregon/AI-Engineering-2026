"""Wiring and compilation of the estimation graph.

The topology is the whole point of this session, so it is written once, here,
and nowhere else. Five nodes in sequence and one decision:

    START → extract_requirements → classify_components → search_budgets
          → generate_estimate → validate_and_consolidate ─┬─ validated → END
                                                          └─ otherwise → flag_for_review → END

The one conditional edge is a real decision point (did the guardrails pass?),
not a formality. Adding more of them for things the nodes already know is how a
graph becomes harder to read than the loop it replaced.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.domain.graph.state import EstimationState

NodeMap = dict[str, Callable[[EstimationState], Awaitable[dict]]]


def route_after_validation(state: EstimationState) -> str:
    """Where to go once the guardrails have run.

    Reads the status the validator set — the routing lives in the edge, so the
    node never has to know what comes after it.
    """
    return END if state.get("status") == "validated" else "flag_for_review"


def build_graph(nodes: NodeMap, *, checkpointer: Any | None = None):
    """Compile the graph over ``nodes``, persisting to ``checkpointer``."""
    builder = StateGraph(EstimationState)
    for name, node in nodes.items():
        builder.add_node(name, node)

    builder.add_edge(START, "extract_requirements")
    builder.add_edge("extract_requirements", "classify_components")
    builder.add_edge("classify_components", "search_budgets")
    builder.add_edge("search_budgets", "generate_estimate")
    builder.add_edge("generate_estimate", "validate_and_consolidate")
    builder.add_conditional_edges(
        "validate_and_consolidate",
        route_after_validation,
        {END: END, "flag_for_review": "flag_for_review"},
    )
    builder.add_edge("flag_for_review", END)

    return builder.compile(checkpointer=checkpointer)
