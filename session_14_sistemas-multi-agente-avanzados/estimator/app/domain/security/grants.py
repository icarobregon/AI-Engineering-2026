"""Who may call what: least privilege as data, verified at startup.

The grant table is the point of the whole multi-agent split. A single agent with
every tool has one decision space and its error rate grows with the number of
options; four agents with one tool each cannot pick the wrong tool, because
there is no wrong tool to pick. That guarantee is only real if something checks
it, so the table lives here as data and ``verify_tool_grants`` reads it against
the agents actually wired into the graph.

**Why a decorator that returns the same function.** ``@grants(...)`` stamps the
declared tools onto the node and hands the very same object back — no wrapper.
LangGraph reads a node's ``Command[Literal[...]]`` return annotation via
``get_type_hints``, which resolves names against the function's own
``__globals__``; a wrapper defined in this module would resolve them here
instead, lose the annotation, and silently disable both the mermaid diagram and
the compile-time check that a routing target exists. Nothing warns you.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum


class ConfigurationError(RuntimeError):
    """An agent was wired with a tool it was never granted."""


class ToolRisk(str, Enum):
    """What a tool can do to the world, which is what decides how it is governed.

    The line that matters runs between the first two and the last two. ``PURE``
    and ``READ`` are recoverable: a wrong call costs tokens and a retry. ``WRITE``
    and ``EXTERNAL`` are not — an email to a client cannot be un-sent — and an
    irreversible action is not a validation problem. It is routed to the human
    gate that already exists, triggered by a different signal. No tool in this
    system is one of those yet; the taxonomy is here because the day one appears,
    where it belongs has to already be decided.
    """

    PURE = "pure"  # no side effects at all: calculate_estimate, validate_estimate
    READ = "read"  # reads the world: search_budgets
    WRITE = "write"  # mutates stored state
    EXTERNAL = "external"  # acts on the world outside this system


# Classified by what the implementation in app/generation/agentic/agent_tools.py
# actually does, not by what its name suggests: validate_estimate only reports on
# numbers it is handed, so it touches nothing and is PURE.
TOOL_RISK: dict[str, ToolRisk] = {
    "search_budgets": ToolRisk.READ,
    "calculate_estimate": ToolRisk.PURE,
    "validate_estimate": ToolRisk.PURE,
}


# The supervisor holds NO tools on purpose: an agent that routes AND works is
# the overloaded node this topology exists to break up. The extractor holds none
# either — it has the model, and the model is not a privilege in this sense.
AGENT_TOOL_GRANTS: dict[str, frozenset[str]] = {
    "supervisor": frozenset(),
    "requirements_extractor": frozenset(),
    "budget_searcher": frozenset({"search_budgets"}),
    "estimate_generator": frozenset({"calculate_estimate"}),
    "coherence_validator": frozenset({"validate_estimate"}),
    "human_review_gate": frozenset(),
    "finalize": frozenset(),
}


def grants(*tool_names: str) -> Callable[[Callable], Callable]:
    """Declare the tools a node is allowed to call, on the node itself."""

    def decorate(node: Callable) -> Callable:
        node.tool_names = frozenset(tool_names)
        return node

    return decorate


def declared_tools(node: Callable) -> frozenset[str]:
    """The tools ``node`` declares. Undecorated means none, which is the safe read."""
    return getattr(node, "tool_names", frozenset())


def verify_tool_grants(agents: dict[str, Callable]) -> None:
    """Fail the DEPLOY if any agent was wired with a tool it was not granted.

    Startup, not request time, and an exception rather than a log line: a
    mis-granted agent is a configuration error, and a service that answers 503
    would blur it into "Postgres is down", which is the one signal that endpoint
    already carries.
    """
    for name, node in agents.items():
        if name not in AGENT_TOOL_GRANTS:
            raise ConfigurationError(f"Agent {name!r} has no entry in AGENT_TOOL_GRANTS")
        granted = AGENT_TOOL_GRANTS[name]
        ungranted = declared_tools(node) - granted
        if ungranted:
            raise ConfigurationError(f"Agent {name!r} has ungranted tools: {sorted(ungranted)}")
        unknown = declared_tools(node) - set(TOOL_RISK)
        if unknown:
            raise ConfigurationError(
                f"Agent {name!r} declares tools with no risk classification: {sorted(unknown)}"
            )
