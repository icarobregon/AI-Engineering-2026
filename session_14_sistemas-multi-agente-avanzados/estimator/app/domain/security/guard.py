"""Deterministic validation of an action before it runs.

The prompt is not a security mechanism. The model is the caller, and a caller
does not get to validate itself — so every argument an agent wants to send is
checked here, in plain Python, against rules that are unit-testable and cannot
be talked out of.

Two checks, in order. The privilege check asks whether this agent may call this
tool at all; the argument rules ask whether THIS call is well formed. They are
separate because they fail for different reasons and a reader of the audit log
needs to tell them apart: the first means the graph is wired wrong, the second
means the model produced something the domain does not accept.

Rules only for what the three real tools actually take. A rule for a tool that
does not exist reads like coverage and is worth less than nothing, because it
makes the file look complete.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.domain.security.grants import AGENT_TOOL_GRANTS

# A merged mega-query is the documented failure of search_budgets: one query
# covering a backend, an ERP integration and a mobile app retrieves an average
# that describes none of them. Length is the cheap proxy for it.
_MAX_QUERY_CHARS = 400
# Engineer-hours of a historical analogue. Below the floor it is not a subsystem;
# above the ceiling it is a whole project and comparing against it is a category
# error. Same band the estimate itself is checked against.
_MIN_REFERENCE_HOURS = 1.0
_MAX_REFERENCE_HOURS = 10_000.0


@dataclass(frozen=True)
class ActionRequest:
    """One agent's intent to call one tool with one set of arguments."""

    agent: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    # Carried explicitly rather than read from a ContextVar: the graph already
    # has it in the state, and an argument that is passed is an argument a test
    # can set.
    estimation_id: str = ""


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    reason: str


def _finite_positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _check_search_budgets(args: dict[str, Any]) -> str | None:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return "search_budgets needs a non-empty query"
    if len(query) > _MAX_QUERY_CHARS:
        return (
            f"search_budgets query is {len(query)} chars, over the "
            f"{_MAX_QUERY_CHARS} limit: it describes more than one component"
        )
    filters = args.get("filters")
    if filters is not None and not isinstance(filters, dict):
        return "search_budgets filters must be an object or null"
    return None


def _check_calculate_estimate(args: dict[str, Any]) -> str | None:
    components = args.get("components")
    if not isinstance(components, list) or not components:
        return "calculate_estimate needs at least one component"
    names: list[str] = []
    for component in components:
        name = (component or {}).get("name")
        if not isinstance(name, str) or not name.strip():
            return "calculate_estimate needs a name on every component"
        names.append(name)
        amounts = (component or {}).get("reference_amounts") or []
        if not isinstance(amounts, list):
            return f"reference_amounts for {name!r} must be a list"
        for amount in amounts:
            if not _finite_positive(amount):
                return f"reference_amounts for {name!r} contains a non-positive value: {amount!r}"
            if not (_MIN_REFERENCE_HOURS <= amount <= _MAX_REFERENCE_HOURS):
                return (
                    f"reference_amounts for {name!r} contains {amount}h, outside the "
                    f"plausible band ({_MIN_REFERENCE_HOURS}-{_MAX_REFERENCE_HOURS}h)"
                )
    # The name is the join key on the way back out of the tool. Two components
    # sharing one would merge their hours into whichever line was written last —
    # silently, and with a total that still adds up.
    if len(set(names)) != len(names):
        return "calculate_estimate was given two components with the same name"
    return None


def _check_validate_estimate(args: dict[str, Any]) -> str | None:
    components = args.get("components")
    if not isinstance(components, list) or not components:
        return "validate_estimate needs the breakdown it is validating"
    total = args.get("total_hours")
    if not isinstance(total, (int, float)) or not math.isfinite(total) or total < 0:
        return f"validate_estimate needs a finite, non-negative total_hours, got {total!r}"
    return None


_ARGUMENT_RULES = {
    "search_budgets": _check_search_budgets,
    "calculate_estimate": _check_calculate_estimate,
    "validate_estimate": _check_validate_estimate,
}


def guard_action(request: ActionRequest) -> GuardDecision:
    """Decide whether ``request`` may run, and say why when it may not."""
    if request.tool not in AGENT_TOOL_GRANTS.get(request.agent, frozenset()):
        return GuardDecision(False, f"{request.agent} is not granted {request.tool}")

    rule = _ARGUMENT_RULES.get(request.tool)
    if rule is None:
        # A granted tool with no rule is a gap in this file, not permission.
        return GuardDecision(False, f"{request.tool} has no argument rules declared")

    problem = rule(request.args)
    if problem is not None:
        return GuardDecision(False, problem)

    return GuardDecision(True, "ok")
