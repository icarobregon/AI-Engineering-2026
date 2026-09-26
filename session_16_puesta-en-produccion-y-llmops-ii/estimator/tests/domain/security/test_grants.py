"""Least privilege, checked at startup.

A grant nobody verifies is a comment. These pin that the verification actually
fails a deploy, because the alternative — noticing at request time — means the
mis-granted agent has already run.
"""

from __future__ import annotations

import pytest

from app.domain.security.grants import (
    AGENT_TOOL_GRANTS,
    TOOL_RISK,
    ConfigurationError,
    ToolRisk,
    declared_tools,
    grants,
    verify_tool_grants,
)


def test_the_decorator_returns_the_same_function_object():
    """Not a wrapper, and that is load-bearing.

    LangGraph reads a node's ``Command[Literal[...]]`` return annotation through
    ``get_type_hints``, which resolves names against the function's own
    ``__globals__``. A wrapper defined in the grants module would resolve them
    there instead, silently lose the annotation, and take the mermaid diagram and
    the compile-time unknown-target check with it.
    """

    async def node(state):
        return state

    assert grants("search_budgets")(node) is node
    assert node.tool_names == frozenset({"search_budgets"})


def test_an_undecorated_node_declares_nothing():
    def node(state):
        return state

    assert declared_tools(node) == frozenset()


def test_the_supervisor_and_the_extractor_hold_no_business_tools():
    # A supervisor that routes AND works is the overloaded node this topology
    # exists to break up; the extractor has the model, which is not a privilege.
    assert AGENT_TOOL_GRANTS["supervisor"] == frozenset()
    assert AGENT_TOOL_GRANTS["requirements_extractor"] == frozenset()


def test_every_specialist_holds_exactly_one_tool():
    for agent in ("budget_searcher", "estimate_generator", "coherence_validator"):
        assert len(AGENT_TOOL_GRANTS[agent]) == 1


def test_no_tool_is_granted_to_two_agents():
    granted = [tool for tools in AGENT_TOOL_GRANTS.values() for tool in tools]

    assert len(granted) == len(set(granted))


def test_every_granted_tool_is_classified_by_risk():
    for tools in AGENT_TOOL_GRANTS.values():
        assert tools <= set(TOOL_RISK)


def test_no_tool_in_this_system_touches_the_world():
    # The day one does, it does not get a validation rule — it gets routed to
    # the human gate that already exists.
    assert set(TOOL_RISK.values()) <= {ToolRisk.PURE, ToolRisk.READ}


def test_an_agent_wired_with_an_ungranted_tool_fails_the_deploy():
    @grants("calculate_estimate")
    async def budget_searcher(state):
        return state

    with pytest.raises(ConfigurationError, match="ungranted"):
        verify_tool_grants({"budget_searcher": budget_searcher})


def test_an_agent_nobody_granted_anything_to_fails_the_deploy():
    async def rogue_agent(state):
        return state

    with pytest.raises(ConfigurationError, match="no entry"):
        verify_tool_grants({"rogue_agent": rogue_agent})


def test_a_tool_with_no_risk_classification_fails_the_deploy():
    @grants("send_estimate_email")
    async def budget_searcher(state):
        return state

    # It would also fail the grant check; asserting the message keeps the two
    # failures distinguishable when one of them starts firing in CI.
    with pytest.raises(ConfigurationError):
        verify_tool_grants({"budget_searcher": budget_searcher})


def test_the_real_agent_map_passes(fake_llm, fake_backend):
    from tests.domain.graph.conftest import build_test_agents

    verify_tool_grants(build_test_agents(fake_llm, fake_backend))
