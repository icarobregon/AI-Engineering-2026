"""Loop mechanics for the Session 12 agent, against a scripted fake client.

What is being tested is the ida-y-vuelta itself, so the fake ``AsyncOpenAI`` is
scripted turn by turn: it hands back function calls, records what we sent, and
finally answers without calling anything. No network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.generation.agentic.agent_loop import (
    SYSTEM_PROMPT,
    AgentRunError,
    run_estimation_agent,
)
from app.generation.agentic.agent_schemas import AgentEstimate, EstimatedComponent


# --- the fake client --------------------------------------------------------


@dataclass
class FakeFunctionCall:
    name: str
    arguments: str
    call_id: str
    type: str = "function_call"


@dataclass
class FakeSummary:
    text: str


@dataclass
class FakeReasoning:
    summary: list[FakeSummary]
    type: str = "reasoning"


@dataclass
class FakeResponse:
    id: str
    output: list[Any]


@dataclass
class FakeParsed:
    output_parsed: AgentEstimate | None


@dataclass
class FakeResponses:
    """Returns the scripted turns in order and records every call it received."""

    turns: list[list[Any]]
    calls: list[dict] = field(default_factory=list)
    parse_calls: list[dict] = field(default_factory=list)

    async def create(self, **kwargs) -> FakeResponse:
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.turns) - 1)
        return FakeResponse(id=f"resp_{len(self.calls)}", output=self.turns[index])

    async def parse(self, **kwargs) -> FakeParsed:
        self.parse_calls.append(kwargs)
        return FakeParsed(
            output_parsed=AgentEstimate(
                project="RUTA",
                components=[
                    EstimatedComponent(
                        name="Backend",
                        estimated_hours=1322.5,
                        rationale="2 analogues",
                        grounded=True,
                    )
                ],
                total_hours=1322.5,
                notes="",
            )
        )


@dataclass
class FakeClient:
    responses: FakeResponses


async def _backend(query, **_kw):
    return [
        {
            "id": 1,
            "content_preview": "historical item",
            "sector": "logistics",
            "budget_id": "BUD-1",
            "estimated_hours": 1150.0,
            "distance": 0.2,
        }
    ]


def _call(name: str, args: dict, call_id: str) -> FakeFunctionCall:
    return FakeFunctionCall(name=name, arguments=json.dumps(args), call_id=call_id)


# --- the loop ---------------------------------------------------------------


async def test_loop_runs_tools_until_the_model_stops_asking():
    turns = [
        # Turn 1: two searches at once, with a reasoning summary.
        [
            FakeReasoning(summary=[FakeSummary(text="Four components; searching each.")]),
            _call("search_budgets", {"query": "logistics backend", "filters": None}, "c1"),
            _call("search_budgets", {"query": "SAP integration", "filters": None}, "c2"),
        ],
        # Turn 2: cost them.
        [
            _call(
                "calculate_estimate",
                {"components": [{"name": "Backend", "reference_amounts": [1150.0]}]},
                "c3",
            )
        ],
        # Turn 3: nothing left to ask — natural stop.
        [],
    ]
    client = FakeClient(responses=FakeResponses(turns=turns))

    estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="gpt-5-mini", max_iterations=10
    )

    assert [step.tool for step in trace.steps] == [
        "search_budgets",
        "search_budgets",
        "calculate_estimate",
    ]
    assert trace.stop_reason == "natural"
    assert estimate.project == "RUTA"
    # The reasoning summary of the turn is attached to that turn's steps.
    assert "Four components" in trace.steps[0].reasoning


async def test_every_tool_result_is_returned_with_its_own_call_id():
    turns = [
        [
            _call("search_budgets", {"query": "a", "filters": None}, "call_a"),
            _call("search_budgets", {"query": "b", "filters": None}, "call_b"),
        ],
        [],
    ]
    client = FakeClient(responses=FakeResponses(turns=turns))
    await run_estimation_agent("transcript", client=client, backend=_backend, model="m")

    second_call = client.responses.calls[1]
    outputs = second_call["input"]
    assert [o["call_id"] for o in outputs] == ["call_a", "call_b"]
    assert all(o["type"] == "function_call_output" for o in outputs)


async def test_chaining_resends_instructions_and_links_the_previous_response():
    turns = [[_call("search_budgets", {"query": "a", "filters": None}, "c1")], []]
    client = FakeClient(responses=FakeResponses(turns=turns))
    await run_estimation_agent("transcript", client=client, backend=_backend, model="m")

    first, second = client.responses.calls[0], client.responses.calls[1]
    assert first["input"] == "transcript"
    assert "previous_response_id" not in first
    # instructions do NOT travel with previous_response_id: they are re-sent.
    assert second["instructions"] == SYSTEM_PROMPT
    assert second["previous_response_id"] == "resp_1"
    assert client.responses.parse_calls[0]["instructions"] == SYSTEM_PROMPT
    # Natural stop: nothing is owed, so the closing call carries only the ask.
    assert [i["role"] for i in client.responses.parse_calls[0]["input"]] == ["user"]


async def test_max_iterations_stops_a_model_that_never_finishes():
    # A single scripted turn that always asks for another search: without the
    # safeguard this loops forever.
    turns = [[_call("search_budgets", {"query": "again", "filters": None}, "c1")]]
    client = FakeClient(responses=FakeResponses(turns=turns))

    _estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="m", max_iterations=3
    )

    assert trace.stop_reason == "max_iterations"
    assert trace.iterations == 3
    assert len(trace.steps) == 3
    # No turn is solicited that there is no iteration left to answer: exactly one
    # create per iteration, and the last tool outputs ride along with the closing
    # call. Chaining onto an unanswered function_call is what the API rejects.
    assert len(client.responses.calls) == 3
    parse_input = client.responses.parse_calls[0]["input"]
    assert parse_input[0]["type"] == "function_call_output"
    assert parse_input[0]["call_id"] == "c1"
    assert parse_input[-1]["role"] == "user"


async def test_malformed_tool_arguments_do_not_crash_the_loop():
    broken = FakeFunctionCall(name="calculate_estimate", arguments="{not json", call_id="c1")
    client = FakeClient(responses=FakeResponses(turns=[[broken], []]))

    _estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="m"
    )

    assert trace.steps[0].error is True
    assert trace.stop_reason == "natural"


async def test_trace_renders_the_required_step_format():
    turns = [[_call("search_budgets", {"query": "logistics backend", "filters": None}, "c1")], []]
    client = FakeClient(responses=FakeResponses(turns=turns))
    _estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="m"
    )

    rendered = trace.render()
    assert "STEP 1" in rendered
    assert "reasoning:" in rendered
    assert "action: search_budgets(" in rendered
    assert "observation:" in rendered


async def test_parallel_calls_share_a_turn_and_do_not_repeat_the_reasoning():
    turns = [
        [
            FakeReasoning(summary=[FakeSummary(text="Two components; searching both.")]),
            _call("search_budgets", {"query": "a", "filters": None}, "c1"),
            _call("search_budgets", {"query": "b", "filters": None}, "c2"),
        ],
        [],
    ]
    client = FakeClient(responses=FakeResponses(turns=turns))
    _estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="m"
    )

    assert [step.iteration for step in trace.steps] == [1, 1]
    # Both steps keep the reasoning; only the rendering collapses the repeat.
    assert all("Two components" in step.reasoning for step in trace.steps)
    rendered = trace.render()
    assert rendered.count("Two components") == 1
    assert "same turn as STEP 1" in rendered


async def test_a_first_turn_with_no_tool_call_is_not_a_natural_stop():
    # The model answered from the transcript alone: same exit, different verdict.
    # An estimate with no tool call behind it is ungrounded by construction, and
    # the trace has to say so rather than claim the job finished normally.
    client = FakeClient(responses=FakeResponses(turns=[[]]))
    _estimate, trace = await run_estimation_agent(
        "transcript", client=client, backend=_backend, model="m"
    )
    assert trace.stop_reason == "no_tool_calls"
    assert trace.steps == []


async def test_an_unparsable_final_answer_raises_but_keeps_the_trace():
    """output_parsed is Optional in the SDK: None on a refusal or an incomplete
    response. Returning it as an AgentEstimate would surface as an AttributeError
    several frames from the cause, and would discard a run that was already paid
    for in full."""

    class UnparsedResponses(FakeResponses):
        async def parse(self, **kwargs):
            self.parse_calls.append(kwargs)
            return FakeParsed(output_parsed=None)

    turns = [[_call("search_budgets", {"query": "a", "filters": None}, "c1")], []]
    client = FakeClient(responses=UnparsedResponses(turns=turns))

    with pytest.raises(AgentRunError) as excinfo:
        await run_estimation_agent("transcript", client=client, backend=_backend, model="m")

    trace = excinfo.value.trace
    assert trace.stop_reason == "unparsed_final"
    assert [step.tool for step in trace.steps] == ["search_budgets"]
    assert "STEP 1" in trace.render()
