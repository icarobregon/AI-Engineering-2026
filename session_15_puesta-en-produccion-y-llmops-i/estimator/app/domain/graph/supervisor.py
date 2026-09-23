"""The supervisor: the only node that decides what happens next.

This is what separates a workflow from an agentic system. In Session 13 the
order lived in the edges — written once, in code, identical for every
transcript. Here it is decided at runtime, one hop at a time, and the shape of
the run only exists afterwards, in ``routing_trail``.

**Hybrid on purpose.** Four of the five transitions are preconditions, not
judgements: you cannot search for budgets before you know what the components
are. Paying a model to rediscover that on every run buys nothing and adds a
failure mode. So the rules handle the preconditions and the model is asked
exactly one question — the one this domain genuinely has an opinion about: the
validator found the evidence thin, so is the right move to search again with
different queries, or to accept what we have and let the human gate decide?

**It holds no business tools.** An agent that routes *and* works is the
overloaded node this topology exists to break up.

**Preconditions read the TRAIL, not the output fields.** "Has the searcher run?"
and "did the searcher find anything?" are different questions, and conflating
them is a live bug: a component with no comparable budget in the corpus is a
legitimate outcome, and a supervisor that dispatches the searcher again every
time ``budget_matches`` is empty loops until the routing budget dies — never
reaching the human gate, which is precisely where a run with no precedent
belongs.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal

import logfire
import structlog
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.domain.graph.digest import agents_that_acted, build_state_digest
from app.domain.graph.llm import stamp_llm
from app.domain.graph.state import EstimationState
from app.domain.security.grants import grants

log = structlog.get_logger()

AgentName = Literal[
    "requirements_extractor",
    "budget_searcher",
    "estimate_generator",
    "coherence_validator",
    "human_review_gate",
    "finalize",
]

# How many times the searcher may be sent back out for the same estimation. One
# retry with different wording is a second opinion and does find things; a third
# is the supervisor going in circles on evidence that is simply not there.
_MAX_BUDGET_SEARCHES = 2

# The same set, as data, so a hallucinated destination can be caught at runtime.
# The Literal above is a compile-time check and the model is not a compiler: a
# Command(goto="ghost_agent") does not raise — LangGraph logs "wrote to unknown
# channel" and the graph ends with a plausible, empty-looking result.
AGENT_NAMES: frozenset[str] = frozenset(AgentName.__args__)


class SupervisorDecision(BaseModel):
    """A closed decision. The model picks a member of the set or nothing at all."""

    next_agent: Literal["budget_searcher", "human_review_gate"] = Field(
        description="The specialist that must act next."
    )
    reason: str = Field(description="Why this specialist, in one sentence.")


# The question, split into the three parts every router needs separately: the
# framing, the options with their descriptions, and the bias between them.
#
# It reads as one prose block to a chat model and it used to BE one. The split
# is what lets a decision model take the same question without a second copy of
# it: TypeSafe's evaluate endpoint wants `instructions` and `criteria` as
# distinct fields, and a paraphrase living next to the original is a prompt that
# drifts. ``compose_supervisor_prompt`` puts it back together for the text path,
# so both routers are asked the same thing by construction.
SUPERVISOR_INSTRUCTIONS = """\
You coordinate a software estimation pipeline. Every mechanical step has already \
run: requirements are extracted, budgets have been searched, an estimate exists \
and it has been validated. One judgement is left.

The validator reported concerns about the evidence behind the estimate. Choose:\
"""

ROUTING_CRITERIA: dict[str, str] = {
    "budget_searcher": (
        "the gaps look like a RETRIEVAL failure. The components that came back "
        "unbacked are ordinary work that a historical corpus would be expected to "
        "contain, so searching again with different wording is likely to find them."
    ),
    "human_review_gate": (
        "the gaps look REAL. The unbacked work has no precedent in this company's "
        "history, or the concerns are about coherence rather than coverage, and no "
        "amount of re-searching will change that. A person should look at it."
    ),
}

# Not a criterion: it is the prior BETWEEN them, and it belongs to neither
# option's description. A text model reads it as the last paragraph; a decision
# model gets it in `instructions`, which is the only field TypeSafe offers that
# is not attached to one choice.
SUPERVISOR_BIAS = """\
Searching again costs a full retrieval pass and delays the estimate. Prefer the \
human gate unless you have a specific reason to believe the corpus contains what \
was missed.
"""


def compose_supervisor_prompt(instructions: str, criteria: dict[str, str], bias: str) -> str:
    """The three parts as the single prose block the text router is given."""
    options = "\n".join(f'- "{name}" — {text}' for name, text in criteria.items())
    return f"{instructions}\n\n{options}\n\n{bias}"


def routing_facts(state: EstimationState, validation: dict) -> str:
    """The counts behind the decision, as a sentence, straight from the state.

    A text router writes its own reason and names these numbers inside it. A
    decision model returns a choice and a probability and no prose at all, so
    without this its trail entry would read "JEV chose human_review_gate (0.85)"
    — a hop whose only consumer is the person reading the audit table.

    Built in code rather than asked for, which makes it the one part of the
    reason that cannot be wrong: a model can misreport how many components came
    back unbacked, ``len()`` cannot.
    """
    return (
        f"{len(state.get('components') or [])} componentes, "
        f"{len(state.get('budget_matches') or [])} referencias, "
        f"confianza {state.get('confidence')}, "
        f"{len(validation.get('concerns') or [])} avisos del validador"
    )


def build_supervisor(
    *,
    ask_router: Any,
    max_routing_steps: int,
) -> Callable[[EstimationState], Awaitable[Command]]:
    """Bind the router's collaborators and return the supervisor node.

    ``ask_router`` is the seam, and it is a callable rather than a model client
    on purpose — the same shape ``search_tool`` and ``validate_tool`` already
    arrive in. This node must not learn that a vendor called TypeSafe exists,
    nor which model string is in force: both are resolved in the composition
    root, which is the only place allowed to know (ARCHITECTURE.md §3). What
    comes back is ``(next_agent, reason, meta)``.
    """

    def _bump(state: EstimationState, decision: dict) -> dict:
        return {
            "routing_steps": state.get("routing_steps", 0) + 1,
            "routing_trail": [decision],
        }

    def _route(
        state: EstimationState, span, agent: str, reason: str, router: str | None = None
    ) -> Command:
        decision = {"next_agent": agent, "reason": reason}
        # Only on the hops a model decided. A rule hop carries no router, and
        # writing None there would put a column in the trail that is empty on
        # four rows out of five — the same reason stamp_llm skips absent values.
        # It is also the only record of WHICH model routed: without it "does the
        # decision model route better than the text one" is not a question the
        # stored runs can answer.
        if router is not None:
            decision["router"] = router
        update = _bump(state, decision)
        if agent == "budget_searcher" and state.get("estimate") is not None:
            # Sending the searcher back out invalidates everything priced from
            # the old evidence. Clearing it here is what makes the generator's
            # and the validator's preconditions ("is your output there?") true
            # again — without it the supervisor would see a complete run, ask the
            # model the same question a second time, and loop.
            update |= {"estimate": None, "validation": None, "confidence": None}
        span.set_attribute("next_agent", agent)
        span.set_attribute("reason", reason)
        log.info("supervisor_routed", next_agent=agent, reason=reason)
        return Command(goto=agent, update=update)

    @grants()
    async def supervisor(state: EstimationState) -> Command[AgentName]:
        with logfire.span("supervisor.route") as span:
            steps = state.get("routing_steps", 0)
            span.set_attribute("routing_steps", steps)

            # Hard ceiling, checked first: a confused router must not be able to
            # burn the API budget. recursion_limit cannot do this job — LangGraph
            # counts it per invoke, so a run that pauses for a human and resumes
            # gets a fresh one every time. This counter is in the checkpoint.
            if steps >= max_routing_steps:
                span.set_attribute("routing_budget_exhausted", True)
                log.warning("supervisor_budget_exhausted", routing_steps=steps)
                return Command(
                    goto="finalize",
                    update=_bump(
                        state,
                        {
                            "next_agent": "finalize",
                            "reason": f"routing budget exhausted at {steps} steps",
                        },
                    ),
                )

            acted = agents_that_acted(state)

            # --- Deterministic preconditions: no model call buys anything here.
            #
            # The first two ask whether the agent HAS RUN; the next two ask
            # whether its output is there. That asymmetry is deliberate. The
            # extractor and the searcher can legitimately produce nothing — a
            # meeting with no concrete requirement, a component with no analogue
            # in the corpus — so reading their output fields would dispatch them
            # forever. The generator and the validator always produce something,
            # so an absent output means either "not yet" or "invalidated by a
            # second search", and both want the same answer: run it.
            if "requirements_extractor" not in acted:
                return _route(state, span, "requirements_extractor", "nothing read yet")
            if "budget_searcher" not in acted:
                return _route(state, span, "budget_searcher", "no references gathered yet")
            if state.get("estimate") is None:
                return _route(state, span, "estimate_generator", "no estimate yet")
            if state.get("validation") is None:
                return _route(state, span, "coherence_validator", "estimate not validated yet")

            validation = state.get("validation") or {}
            if validation.get("is_coherent"):
                return _route(state, span, "human_review_gate", "validation clean")

            # One re-search is a second opinion; a third is a loop. Counting the
            # searcher's own appearances bounds it independently of the global
            # routing budget, so the ceiling stays the emergency brake it is.
            searches = sum(
                1
                for entry in state.get("routing_trail") or []
                if entry.get("next_agent") == "budget_searcher"
            )
            if searches >= _MAX_BUDGET_SEARCHES:
                return _route(
                    state, span, "human_review_gate", "evidence gaps persist after re-searching"
                )

            # --- Genuine ambiguity: here the model earns its keep.
            next_agent, reason, meta = await ask_router(
                state_text=(
                    f"{build_state_digest(state)}\n\n"
                    f"concerns:\n" + "\n".join(f"- {c}" for c in validation.get("concerns") or [])
                ),
                instructions=SUPERVISOR_INSTRUCTIONS,
                criteria=ROUTING_CRITERIA,
                bias=SUPERVISOR_BIAS,
                facts=routing_facts(state, validation),
            )
            stamp_llm(span, meta)

            if next_agent not in AGENT_NAMES:
                # Not reachable through the Literal, but the Literal is enforced
                # by the parser and a parser can be swapped. A bad goto does not
                # raise in LangGraph; it ends the run with a state that looks
                # finished. Failing into the gate is the safe direction.
                log.error("supervisor_unknown_agent", next_agent=next_agent)
                return _route(state, span, "human_review_gate", f"unknown route {next_agent!r}")

            return _route(state, span, next_agent, reason, router=meta.get("model"))

    return supervisor
