"""Wiring and compilation of the multi-agent estimation system.

One declared edge, and that is the point:

    START → supervisor

Everything else travels inside a ``Command``, which moves the control AND writes
the state in the same return value. The graph no longer describes a flow — it
describes a set of capabilities and a router — and the shape of any particular
run only exists afterwards, recorded in ``routing_trail``.

**The checkpointer is required, not optional.** ``compile(checkpointer=None)``
with an ``interrupt()`` in the graph does not raise: the run silently halts, the
result looks like a truncated success, and the failure only surfaces much later
as ``RuntimeError: Cannot use Command(resume=...) without checkpointer``. Nothing
in LangGraph will tell you, so it is asserted here.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from langgraph.graph import START, StateGraph

from app.domain.graph.state import EstimationState

AgentMap = dict[str, Callable[[EstimationState], Awaitable[Any]]]


def build_graph(agents: AgentMap, *, checkpointer: Any):
    """Compile the supervisor/worker graph over ``agents``, persisting to ``checkpointer``.

    ``agents`` is injected rather than imported: ``app/domain/graph`` may not
    reach the composition root (ARCHITECTURE.md §3), and one factory filled in
    one place is what stops the demo script and the service from drifting apart.
    """
    if checkpointer is None:
        raise ValueError(
            "The multi-agent graph requires a checkpointer: without one interrupt() "
            "halts the run and the resume can never happen."
        )

    builder = StateGraph(EstimationState)
    for name, agent in agents.items():
        builder.add_node(name, agent)

    builder.add_edge(START, "supervisor")

    return builder.compile(checkpointer=checkpointer)
