"""Argument validation, and the audit line every action leaves behind.

The prompt is not a security mechanism: the model is the caller, and a caller
does not validate itself. These are the rules that do, in plain Python, with no
model anywhere near them.
"""

from __future__ import annotations

import pytest
import structlog

from app.domain.security.audit import (
    ActionDeniedError,
    execute_guarded,
    redact_sensitive,
    summarize,
)
from app.domain.security.guard import ActionRequest, guard_action


def _request(agent: str, tool: str, **args) -> ActionRequest:
    return ActionRequest(agent=agent, tool=tool, args=args, estimation_id="e1")


# --- privilege ----------------------------------------------------------------


def test_an_agent_may_not_call_a_tool_it_was_not_granted():
    decision = guard_action(_request("budget_searcher", "calculate_estimate", components=[]))

    assert not decision.allowed
    assert "not granted" in decision.reason


def test_the_supervisor_may_not_call_anything():
    decision = guard_action(_request("supervisor", "search_budgets", query="anything"))

    assert not decision.allowed


def test_an_agent_that_does_not_exist_is_refused_rather_than_defaulted():
    decision = guard_action(_request("ghost", "search_budgets", query="anything"))

    assert not decision.allowed


# --- search_budgets -----------------------------------------------------------


def test_a_well_formed_search_passes():
    assert guard_action(
        _request("budget_searcher", "search_budgets", query="SAP integration", filters=None)
    ).allowed


def test_an_empty_query_is_refused():
    assert not guard_action(_request("budget_searcher", "search_budgets", query="  ")).allowed


def test_a_merged_mega_query_is_refused():
    """One query covering four components retrieves an average that describes
    none of them — the documented failure of this tool. Length is the cheap
    proxy for it."""
    decision = guard_action(
        _request("budget_searcher", "search_budgets", query="x" * 500, filters=None)
    )

    assert not decision.allowed
    assert "more than one component" in decision.reason


# --- calculate_estimate -------------------------------------------------------


def test_a_well_formed_calculation_passes():
    assert guard_action(
        _request(
            "estimate_generator",
            "calculate_estimate",
            components=[{"name": "c1", "reference_amounts": [90.0, 82.0]}],
        )
    ).allowed


def test_a_component_with_no_references_is_fine_it_is_just_unbudgeted():
    assert guard_action(
        _request(
            "estimate_generator",
            "calculate_estimate",
            components=[{"name": "c1", "reference_amounts": []}],
        )
    ).allowed


def test_a_negative_reference_is_refused():
    decision = guard_action(
        _request(
            "estimate_generator",
            "calculate_estimate",
            components=[{"name": "c1", "reference_amounts": [-40.0]}],
        )
    )

    assert not decision.allowed
    assert "non-positive" in decision.reason


def test_a_reference_larger_than_any_real_subsystem_is_refused():
    decision = guard_action(
        _request(
            "estimate_generator",
            "calculate_estimate",
            components=[{"name": "c1", "reference_amounts": [99_000.0]}],
        )
    )

    assert not decision.allowed
    assert "plausible band" in decision.reason


def test_two_components_with_the_same_name_are_refused():
    """The name is the join key on the way back out of the tool: two components
    sharing one would merge their hours into whichever line was written last,
    silently, with a total that still adds up."""
    decision = guard_action(
        _request(
            "estimate_generator",
            "calculate_estimate",
            components=[
                {"name": "c1", "reference_amounts": [90.0]},
                {"name": "c1", "reference_amounts": [82.0]},
            ],
        )
    )

    assert not decision.allowed
    assert "same name" in decision.reason


def test_a_calculation_with_no_components_is_refused():
    assert not guard_action(
        _request("estimate_generator", "calculate_estimate", components=[])
    ).allowed


# --- validate_estimate --------------------------------------------------------


def test_a_well_formed_validation_passes():
    assert guard_action(
        _request(
            "coherence_validator",
            "validate_estimate",
            components=[{"name": "c1", "estimated_hours": 90.0, "reference_amounts": [90.0]}],
            total_hours=90.0,
        )
    ).allowed


def test_a_validation_with_a_negative_total_is_refused():
    decision = guard_action(
        _request(
            "coherence_validator",
            "validate_estimate",
            components=[{"name": "c1", "estimated_hours": 1.0, "reference_amounts": []}],
            total_hours=-1.0,
        )
    )

    assert not decision.allowed
    assert "total_hours" in decision.reason


# --- audit --------------------------------------------------------------------


def test_the_arguments_keep_their_shape_and_lose_their_payload():
    redacted = redact_sensitive(
        {"query": "x" * 500, "filters": {"sectors": ["logistics", "finance"]}, "top_k": 5}
    )

    assert redacted["query"].endswith("…") and len(redacted["query"]) < 500
    assert redacted["filters"]["sectors"] == "[2 item(s)]"
    # The shape is what makes a log line diagnosable; the meeting inside it is
    # client material that has no business in a log aggregator.
    assert redacted["top_k"] == 5


def test_summarize_prefers_the_tools_own_observation():
    class Result:
        observation = "2 items for 'sap integration'"

    assert summarize(Result()) == "2 items for 'sap integration'"
    assert summarize(object()) == "object"


async def test_a_permitted_action_runs_and_is_logged():
    calls = []

    def tool(**args):
        calls.append(args)
        return "ok"

    result = await execute_guarded(
        _request("budget_searcher", "search_budgets", query="SAP", filters=None), tool
    )

    assert result == "ok"
    assert calls == [{"query": "SAP", "filters": None}]


async def test_a_denied_action_never_reaches_the_tool():
    def tool(**args):  # pragma: no cover - reaching this IS the failure
        raise AssertionError("the guard let an ungranted call through")

    with pytest.raises(ActionDeniedError):
        await execute_guarded(
            _request("budget_searcher", "calculate_estimate", components=[]), tool
        )


async def test_a_denial_is_the_most_valuable_line_in_the_log(capsys):
    """A successful call is expected. A denial is the system telling you an agent
    tried something it was not allowed to do — either a wiring bug or the model
    going somewhere nobody predicted."""
    structlog.configure(
        processors=[structlog.processors.KeyValueRenderer(sort_keys=True)],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    try:
        with pytest.raises(ActionDeniedError):
            await execute_guarded(
                _request("supervisor", "search_budgets", query="anything"), lambda **a: None
            )
    finally:
        structlog.reset_defaults()

    logged = capsys.readouterr().out
    assert "action_denied" in logged
    assert "agent='supervisor'" in logged
    assert "estimation_id='e1'" in logged
