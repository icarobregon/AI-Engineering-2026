"""The routing rules, as pure functions of the state.

The end-to-end tests pin the invariants of a whole run; these pin the decisions
themselves, including the ones a happy run never reaches — the routing budget,
the re-search bound and the hallucinated destination.
"""

from __future__ import annotations

import pytest

from app.domain.graph.digest import agents_that_acted, build_state_digest
from app.domain.graph.supervisor import AGENT_NAMES, SupervisorDecision, build_supervisor


class ScriptedLLM:
    """Answers the supervisor's one question with whatever the test wants."""

    def __init__(self, next_agent: str = "human_review_gate"):
        self.next_agent = next_agent
        self.calls = 0

    def complete_structured(self, **kwargs):
        self.calls += 1
        return (
            SupervisorDecision(next_agent=self.next_agent, reason="scripted"),
            {"model": kwargs.get("model_override")},
        )


def _state(**overrides) -> dict:
    base = {
        "transcript": "t",
        "estimation_id": "e1",
        "routing_steps": 0,
        "routing_trail": [],
        "budget_matches": [],
        "errors": [],
    }
    return base | overrides


def _trail(*agents) -> list[dict]:
    return [{"next_agent": agent, "reason": "x"} for agent in agents]


async def _route(state, *, llm=None, max_routing_steps=8):
    supervisor = build_supervisor(
        llm=llm or ScriptedLLM(), model="m", max_routing_steps=max_routing_steps
    )
    return await supervisor(state)


# --- the deterministic preconditions -----------------------------------------


async def test_an_empty_state_goes_to_the_extractor_without_asking_the_model():
    llm = ScriptedLLM()

    command = await _route(_state(), llm=llm)

    assert command.goto == "requirements_extractor"
    assert llm.calls == 0


async def test_the_searcher_runs_once_the_components_are_known():
    command = await _route(_state(routing_trail=_trail("requirements_extractor")))

    assert command.goto == "budget_searcher"


async def test_a_search_that_found_nothing_is_not_retried_forever():
    """The bug this rule exists to prevent.

    "The searcher has not run" and "the searcher found nothing" are different
    facts, and a supervisor that reads ``budget_matches`` cannot tell them apart:
    a transcript with no precedent in the corpus bounces between the supervisor
    and the searcher until the routing budget dies — never reaching the human
    gate, which is exactly where a run with no precedent belongs.
    """
    state = _state(
        routing_trail=_trail("requirements_extractor", "budget_searcher"), budget_matches=[]
    )

    command = await _route(state)

    assert command.goto == "estimate_generator"


async def test_the_validator_runs_once_an_estimate_exists():
    state = _state(
        routing_trail=_trail("requirements_extractor", "budget_searcher", "estimate_generator"),
        estimate={"total_hours": 10},
    )

    command = await _route(state)

    assert command.goto == "coherence_validator"


async def test_a_clean_validation_goes_straight_to_the_gate_with_no_model_call():
    llm = ScriptedLLM()
    state = _state(
        routing_trail=_trail(
            "requirements_extractor",
            "budget_searcher",
            "estimate_generator",
            "coherence_validator",
        ),
        estimate={"total_hours": 10},
        validation={"is_coherent": True, "concerns": []},
    )

    command = await _route(state, llm=llm)

    assert command.goto == "human_review_gate"
    assert llm.calls == 0


# --- the one judgement the model owns ----------------------------------------


async def test_concerns_are_the_one_case_the_model_decides():
    llm = ScriptedLLM(next_agent="budget_searcher")
    state = _state(
        routing_trail=_trail(
            "requirements_extractor",
            "budget_searcher",
            "estimate_generator",
            "coherence_validator",
        ),
        routing_steps=4,
        estimate={"total_hours": 10},
        validation={"is_coherent": False, "concerns": ["two components unbacked"]},
    )

    command = await _route(state, llm=llm)

    assert llm.calls == 1
    assert command.goto == "budget_searcher"
    # Sending the searcher back out invalidates everything priced from the old
    # evidence; without this the supervisor would see a complete run, ask the
    # same question again and loop.
    assert command.update["estimate"] is None
    assert command.update["validation"] is None


async def test_the_searcher_is_not_sent_out_a_third_time():
    llm = ScriptedLLM(next_agent="budget_searcher")
    state = _state(
        routing_trail=_trail(
            "requirements_extractor",
            "budget_searcher",
            "estimate_generator",
            "coherence_validator",
            "budget_searcher",
            "estimate_generator",
            "coherence_validator",
        ),
        routing_steps=7,
        estimate={"total_hours": 10},
        validation={"is_coherent": False, "concerns": ["still unbacked"]},
    )

    command = await _route(state, llm=llm)

    assert command.goto == "human_review_gate"
    assert llm.calls == 0


# --- the ceilings -------------------------------------------------------------


async def test_the_routing_budget_is_checked_before_any_rule():
    llm = ScriptedLLM()

    command = await _route(_state(routing_steps=8), llm=llm, max_routing_steps=8)

    assert command.goto == "finalize"
    assert llm.calls == 0


async def test_every_decision_is_recorded_with_its_reason():
    command = await _route(_state())

    assert command.update["routing_steps"] == 1
    assert command.update["routing_trail"] == [
        {"next_agent": "requirements_extractor", "reason": "nothing read yet"}
    ]


# --- the closed decision ------------------------------------------------------


def test_the_routing_literal_matches_the_agents_the_graph_has(fake_llm, fake_backend):
    """A destination that is not a node does not raise in LangGraph.

    It logs "wrote to unknown channel" and the run ends with a state that looks
    finished, which is the worst way for a routing typo to fail. The Literal is
    the compile-time half of the defence and this is what keeps it honest.
    """
    from .conftest import build_test_agents

    # Everything the graph has, minus the supervisor: it never routes to itself.
    assert AGENT_NAMES == set(build_test_agents(fake_llm, fake_backend)) - {"supervisor"}


def test_the_decision_model_refuses_a_destination_outside_the_set():
    with pytest.raises(ValueError):
        SupervisorDecision(next_agent="ghost_agent", reason="because")


# --- the digest ---------------------------------------------------------------


def test_the_digest_reports_who_has_acted_not_what_is_empty():
    state = _state(routing_trail=_trail("requirements_extractor", "budget_searcher"))

    digest = build_state_digest(state)

    assert "agents_already_run: ['budget_searcher', 'requirements_extractor']" in digest
    assert "budget_matches_found: 0" in digest


def test_the_digest_survives_a_state_whose_keys_do_not_exist_yet():
    """Only the accumulator channels pre-seed; every other key is simply absent
    until something writes it, so a digest that subscripts raises KeyError on the
    very first superstep — when the supervisor needs it most."""
    assert "routing_steps_so_far: 0" in build_state_digest({})
    assert agents_that_acted({}) == set()
