"""The manual agent loop: reason -> act -> observe, driven by hand.

This is the one place in the codebase that talks to the raw OpenAI **Responses
API** instead of going through ``LLMWrapper``. That is deliberate, not an
oversight: the point of Session 12 is to see what an agent is made of, and every
framework — including our own wrapper — hides exactly the part worth seeing. Do
not "fix" this to use ``LLMWrapper``.

How the loop actually turns
---------------------------
``responses.create`` with our tools does NOT run the tools. It returns
``function_call`` items and stops, waiting for us. So one turn is:

1. read ``response.output``: reasoning summaries (why) + ``function_call`` items (what),
2. run every call we were handed — there can be several in one turn,
3. send each result back as a ``function_call_output`` carrying the SAME ``call_id``,
4. call the API again and repeat.

The loop ends when a turn comes back with no ``function_call`` — the model has
said what it wanted to say — with ``max_iterations`` as a safeguard in case it
never does.

Chaining is **stateful**: ``store=True`` plus ``previous_response_id``, sending
only the new outputs each turn. The server then keeps the conversation, including
the ordering of reasoning items, which the manual variant (re-sending every item
ourselves) gets wrong easily on reasoning models. Two consequences to remember:
``instructions`` do NOT carry over — they are re-sent on every call — and the
transcript is sent once, at the start.

The final answer is a separate ``responses.parse`` call so the estimate comes back
as a validated ``AgentEstimate`` rather than prose we would have to re-parse.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from app.generation.agentic.agent_schemas import AgentEstimate, AgentStep, AgentTrace
from app.generation.agentic.agent_tools import TOOLS, BudgetSearchBackend, dispatch_tool

log = structlog.get_logger()


class AgentRunError(RuntimeError):
    """The run produced no usable estimate — with the trace it got to first.

    Carrying the trace matters: by the time the closing call fails, the run has
    already paid for every tool call and every reasoning turn behind it, and that
    record is the deliverable of this exercise. Losing it to an exception would
    throw away the expensive part to report the cheap part.
    """

    def __init__(self, message: str, trace: AgentTrace) -> None:
        super().__init__(message)
        self.trace = trace


SYSTEM_PROMPT = """\
You are a software estimation agent for a consultancy. You are given the raw \
transcript of a discovery meeting and you produce an effort estimate in \
engineer-hours, grounded in what comparable past projects actually cost.

Method:
1. Read the transcript and identify the distinct components of the project. Two \
pieces are distinct when they are different kinds of work (a business backend, an \
ERP integration, a mobile app and an analytics dashboard are four components, not \
one project).
2. For each component, call search_budgets on its own, with an ENGLISH query \
describing that component alone (the historical corpus is in English, whatever \
language the meeting was held in). Search AT MOST TWICE for the same component: if a second, \
differently worded search still finds nothing comparable, the corpus does not \
cover that work — accept it and move on. Rephrasing a third time costs a turn and \
finds the same nothing.
3. Then call calculate_estimate ONCE, passing every component of the project \
with the hours of the items you retrieved for it. The retrieved items ARE the \
evidence: discard one only when it is about clearly different work. A \
cross-sector analogue still counts — a grocery-delivery routing backend is \
evidence for a logistics backend — so use it and note the mismatch in your \
answer instead of throwing it away. Only a component whose searches came back \
EMPTY goes in with an empty reference_amounts, and only that one may be reported \
as unbudgeted.
4. Call validate_estimate on the result and act on what it reports.
5. Report the estimate: the components, their hours, what backs each number, and \
the total.

Rules:
- Never invent hours. Numbers come from the tools, not from you. If a component \
has no historical backing, say so and leave it unbudgeted.
- Do not merge unrelated components into one search: the result would be an \
average that describes none of them.
- Write your final answer in the language of the transcript.
"""

# Sent on the last turn to close the loop with a typed answer. The model has the
# whole conversation behind it, so this only has to ask for the shape.
FINAL_INSTRUCTION = (
    "Report the final estimate now, using only the numbers the tools returned. "
    "Mark as not grounded any component you found no historical backing for."
)


def _reasoning_summary(output: list[Any]) -> str:
    """Join the reasoning summaries of one turn into a single line.

    Summaries are opt-in (``reasoning.summary='auto'``) and the model does not
    always produce one — an empty string here is normal, not a failure.
    """
    parts: list[str] = []
    for item in output:
        if getattr(item, "type", None) != "reasoning":
            continue
        for entry in getattr(item, "summary", None) or []:
            text = getattr(entry, "text", None)
            if text:
                parts.append(text.strip())
    return " ".join(parts)


def _function_calls(output: list[Any]) -> list[Any]:
    return [item for item in output if getattr(item, "type", None) == "function_call"]


async def run_estimation_agent(
    transcript: str,
    *,
    client: Any,
    backend: BudgetSearchBackend,
    model: str,
    reasoning_effort: str = "medium",
    max_iterations: int = 10,
) -> tuple[AgentEstimate, AgentTrace]:
    """Run the agent over one transcript. Returns the estimate and its trace."""
    trace = AgentTrace(model=model, reasoning_effort=reasoning_effort)
    reasoning = {"effort": reasoning_effort, "summary": "auto"}

    response = await client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=transcript,
        tools=TOOLS,
        reasoning=reasoning,
        store=True,
    )

    step_number = 0
    # Tool outputs still owed to the model if the iteration budget runs out; they
    # ride along with the closing call instead of being left dangling.
    pending_outputs: list = []
    for iteration in range(1, max_iterations + 1):
        trace.iterations = iteration
        calls = _function_calls(response.output)
        if not calls:
            # A first turn with no tool call is not the same thing as a finished
            # job: the model answered from the transcript alone, asked something,
            # or the response came back incomplete. Same exit, different verdict —
            # and the trace has to say which, because an estimate with no tool
            # call behind it is ungrounded by construction.
            trace.stop_reason = "natural" if trace.steps else "no_tool_calls"
            break

        # The model can ask for several tools in one turn — for this agent, one
        # search per component at once. Run them concurrently and answer all of
        # them together; returning a partial set would leave dangling call_ids.
        turn_reasoning = _reasoning_summary(response.output)
        parsed_args = [_safe_json(call.arguments) for call in calls]
        results = await asyncio.gather(
            *(
                dispatch_tool(call.name, args, backend=backend)
                for call, args in zip(calls, parsed_args)
            )
        )

        outputs = []
        for call, args, result in zip(calls, parsed_args, results):
            step_number += 1
            trace.steps.append(
                AgentStep(
                    step=step_number,
                    iteration=iteration,
                    reasoning=turn_reasoning,
                    tool=call.name,
                    arguments=args,
                    observation=result.observation,
                    error=result.error,
                )
            )
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": result.output,
                }
            )

        log.info(
            "agent_iteration",
            iteration=iteration,
            tools=[call.name for call in calls],
            errors=sum(1 for r in results if r.error),
        )

        if iteration == max_iterations:
            # Out of budget with the model still asking for tools. Do NOT solicit
            # another tool turn there is no iteration left to answer: chaining the
            # closing call onto a response whose function_calls have no matching
            # output is rejected by the API ("No tool output found for function
            # call"), which would throw the whole trace away at the exact moment
            # the safeguard is meant to salvage it. These last outputs ride along
            # with the closing call instead — answered, and asked to conclude.
            trace.stop_reason = "max_iterations"
            pending_outputs = outputs
            log.warning("agent_max_iterations", max_iterations=max_iterations)
            break

        response = await client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            previous_response_id=response.id,
            input=outputs,
            tools=TOOLS,
            reasoning=reasoning,
            store=True,
        )

    final = await client.responses.parse(
        model=model,
        instructions=SYSTEM_PROMPT,
        previous_response_id=response.id,
        input=[*pending_outputs, {"role": "user", "content": FINAL_INSTRUCTION}],
        reasoning=reasoning,
        text_format=AgentEstimate,
        store=True,
    )
    estimate = final.output_parsed
    if estimate is None:
        # ParsedResponse.output_parsed is Optional: it is None when the closing
        # response carries no parsed output_text — a refusal, or an `incomplete`
        # status because a reasoning model spent its output budget on reasoning
        # tokens. Returning it as an AgentEstimate would push an AttributeError
        # into the caller's rendering, several frames from the cause.
        trace.stop_reason = "unparsed_final"
        log.error(
            "agent_final_unparsed",
            status=getattr(final, "status", None),
            steps=len(trace.steps),
        )
        raise AgentRunError(
            "The model returned no parsable estimate on the closing call "
            f"(status={getattr(final, 'status', None)}).",
            trace,
        )

    log.info(
        "agent_done",
        iterations=trace.iterations,
        steps=len(trace.steps),
        stop_reason=trace.stop_reason,
    )
    return estimate, trace


def _safe_json(raw: str | None) -> dict[str, Any]:
    """Parse tool arguments, tolerating the model sending malformed JSON.

    A parse failure is not fatal here: it becomes an empty argument dict, the tool
    rejects it, and the error travels back as an observation the model can fix.
    """
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        log.warning("agent_bad_tool_arguments", raw=raw)
        return {}
