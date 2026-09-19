"""The specialists: four agents, one job each, and the terminal.

Every one of them does its work, writes the part of the state it produced, and
hands the baton back to the supervisor. None of them decides who runs next —
that is the supervisor's only job, and moving it into an agent is how a
multi-agent system quietly turns back into the tangled loop it replaced.

**Least privilege is enforced, not described.** ``@grants(...)`` declares the
tools an agent may call, ``verify_tool_grants`` checks the declaration against
the table at startup, and every tool call goes through ``execute_guarded``, which
validates the arguments and writes the audit line. An agent literally cannot
reach a tool it was not granted: the guard refuses it before the call is made.

**The arithmetic is the tool's, the prose is the model's.** ``estimate_generator``
asks ``calculate_estimate`` for the hours and the model only for the rationale,
so the one failure mode this whole pipeline exists to prevent — a model inventing
a number — is not available to it.

**Why a factory instead of module-level functions.** The agents need the LLM
wrapper and the retrieval backend, and ``app/domain/`` may not import
``app.dependencies`` (ARCHITECTURE.md §3: the composition root is imported by
``api/`` and the tests, never by a layer). So the collaborators are bound at
build time and the agents close over them. They stay pure functions of the state
— which is what the graph and the tests care about — and the wiring stays in the
one place that is allowed to know about wiring.

**Import ``Command`` and ``Literal`` at module level.** LangGraph reads each
node's ``Command[Literal[...]]`` return annotation to learn where it can go, via
``get_type_hints`` against the function's own module globals. Under
``from __future__ import annotations`` a ``TYPE_CHECKING`` import resolves to
nothing, the lookup fails, and LangGraph swallows the error: the graph still
runs, but the diagram lies and the compile-time check for an unknown routing
target is gone. Nothing warns you.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Literal

import logfire
import structlog
from langgraph.graph import END
from langgraph.types import Command

from app.domain.graph.llm import stamp_llm, structured_call
from app.domain.graph.schemas import (
    ComponentList,
    EstimateNarrative,
    RequirementList,
    ValidationResult,
)
from app.domain.graph.state import BudgetMatch, Component, EstimationState
from app.domain.security.audit import ActionDeniedError, execute_guarded
from app.domain.security.grants import grants
from app.domain.security.guard import ActionRequest

log = structlog.get_logger()

# How close a retrieved analogue has to be to count as evidence. Mirrors
# AGENT_SEARCH_DISTANCE_THRESHOLD, which is the distance past which the retrieval
# pipeline stops returning rows at all: a match at the cutoff carries no
# confidence, one at zero carries all of it.
_MAX_USEFUL_DISTANCE = 0.6
# References per component past which more evidence stops adding confidence. Two
# independent analogues is the point where a median means something.
_TARGET_REFERENCES_PER_COMPONENT = 2


def _normalise_id(raw: Any) -> str:
    """Read a component id the way the model may have written it.

    A real run returned "[c1]" because the prompt had shown the id inside
    brackets. The identity is ours and it is unambiguous; brackets and stray
    whitespace around it are punctuation, not a different component, and
    rejecting the whole line over them would flag a correct estimate.
    """
    return str(raw or "").strip().strip("[]").strip()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _times_dispatched(state: EstimationState, agent: str) -> int:
    """How many times the supervisor has sent work to ``agent`` in this run."""
    return sum(1 for entry in state.get("routing_trail") or [] if entry.get("next_agent") == agent)


def _unpriced_estimate(components: list[Component]) -> dict:
    """An estimate that admits it has no numbers, rather than no estimate at all.

    Returning ``None`` would leave the generator's own precondition unsatisfied
    and the supervisor would dispatch it again, forever. This shape says the
    same thing honestly: every component present, nothing grounded, nothing
    costed — which is what sends it to a human.
    """
    return {
        "project": "",
        "components": [
            {
                "component_id": c["id"],
                "name": c["name"],
                "estimated_hours": 0.0,
                "grounded": False,
                "rationale": "",
            }
            for c in components
        ],
        "total_hours": 0.0,
        "notes": "The estimate could not be costed; every component is unpriced.",
    }


def _references_by_component(state: EstimationState) -> dict[str, list[float]]:
    """The hours found for each component, keyed by the id WE assigned.

    Keyed by id and never by name: the classifier can hand back two components
    called the same thing, and pooling their references prices both at the
    median of the merged set — two wrong lines with a total that still adds up.
    """
    by_id: dict[str, list[float]] = {}
    for match in state.get("budget_matches") or []:
        by_id.setdefault(match["component_id"], []).append(match["amount"])
    return by_id


EXTRACT_SYSTEM = """\
You read the transcript of a software discovery meeting and list what the client \
actually needs built.

Return one requirement per line of the list: concrete, self-contained, and \
traceable to something said in the meeting. Include constraints that shape the \
work (offline support, an ERP to integrate with, a regulator to satisfy). Leave \
out pleasantries, scheduling talk and anything you inferred but nobody said.

Write each requirement in the language of the transcript.
"""

CLASSIFY_SYSTEM = """\
You group requirements into the components a project would be estimated and \
staffed by.

A component is a unit of work that could be budgeted on its own: a business \
backend, an ERP integration, a mobile app, an analytics dashboard. Requirements \
that belong to the same unit go together; two requirements that are different \
KINDS of work never do, however related they sound.

For each component give:
- `name`: how the meeting refers to it, in the transcript's language.
- `category`: the kind of work.
- `search_query`: the same component described IN ENGLISH for searching a \
historical budget corpus — the work, its technologies and its scope. This one is \
always English, whatever language the meeting was in.
"""

NARRATIVE_SYSTEM = """\
You explain an effort estimate that has already been calculated. You do not \
produce hours and you cannot change them.

For each component you are given its id, its name, the hours assigned to it and \
the historical references behind those hours. Write one line per component \
saying which references back it. A component with no references gets a plain \
statement of the gap — an unbudgeted component is a fact the reader needs, not a \
hole to fill. References from another sector still count as evidence; use them \
and note the mismatch.

Copy each component's `id:` value into `component_id` — just the value, like \
`c1` — one line per component and no more: it is how your text is matched back \
to its evidence.

Write the prose in the language of the transcript.
"""


def build_agents(
    *,
    llm: Any,
    search_backend: Callable[..., Awaitable[list[dict]]],
    search_tool: Callable[..., Awaitable[Any]],
    calculate_tool: Callable[..., Any],
    validate_tool: Callable[..., Any],
    fast_model: str,
    estimate_model: str,
    reasoning_effort: str = "medium",
    estimate_max_tokens: int = 16000,
) -> dict[str, Callable[[EstimationState], Awaitable[Command]]]:
    """Bind the collaborators and return the specialists by name.

    The three tools are injected rather than imported: ``app/domain/graph`` sits
    at conductor level and could legally reach ``app/generation/agentic``, but
    passing them in is what lets a test drive an agent with a double and what
    keeps the ``--stub`` retrieval swap a one-argument change.
    """

    # The S12 tools take their arguments as ONE dict, the way the Responses API
    # hands them over. The guard and the audit log want the arguments themselves,
    # so these adapters are where the two shapes meet — and they are the reason
    # the tools did not have to be rewritten to be redistributed.
    async def _call_search_budgets(**args) -> Any:
        return await search_tool(args, backend=search_backend)

    def _call_calculate_estimate(**args) -> Any:
        return calculate_tool(args)

    def _call_validate_estimate(**args) -> Any:
        return validate_tool(args)

    async def _guarded(agent: str, tool_name: str, args: dict, state: EstimationState, tool):
        return await execute_guarded(
            ActionRequest(
                agent=agent,
                tool=tool_name,
                args=args,
                estimation_id=state.get("estimation_id", ""),
            ),
            tool,
        )

    @grants()
    async def requirements_extractor(
        state: EstimationState,
    ) -> Command[Literal["supervisor"]]:
        """Transcript → what must be built, grouped into units of work.

        No business tools: this one has the model and nothing else. It owns both
        passes because they are one responsibility — reading the meeting — and
        splitting them would buy an extra routing hop and a second LLM-only agent
        with nothing else to distinguish it.
        """
        with logfire.span("agent.requirements_extractor") as span:
            requirements, meta = await structured_call(
                llm,
                system_prompt=EXTRACT_SYSTEM,
                user_message=state["transcript"],
                model=fast_model,
                response_model=RequirementList,
            )
            stamp_llm(span, meta)

            listing = "\n".join(f"- {r}" for r in requirements.requirements)
            classified, meta = await structured_call(
                llm,
                system_prompt=CLASSIFY_SYSTEM,
                user_message=listing,
                model=fast_model,
                response_model=ComponentList,
            )
            span.set_attribute("requirements", len(requirements.requirements))
            span.set_attribute("components", len(classified.components))

        # The id is ours, assigned by position. Everything downstream joins on it.
        components: list[Component] = [
            {
                "id": f"c{index}",
                "name": c.name,
                "category": c.category,
                "search_query": c.search_query,
            }
            for index, c in enumerate(classified.components, start=1)
        ]
        log.info(
            "agent_done",
            agent="requirements_extractor",
            requirements=len(requirements.requirements),
            components=len(components),
        )
        return Command(
            goto="supervisor",
            update={"requirements": requirements.requirements, "components": components},
        )

    @grants("search_budgets")
    async def budget_searcher(state: EstimationState) -> Command[Literal["supervisor"]]:
        """Each component → the historical subsystems comparable to it.

        One call per component, never a merged query: a backend, an ERP
        integration and a mobile app are different kinds of work with different
        costs, and a query that merges them retrieves an average that describes
        none of them. A component whose search fails degrades into ``errors``
        instead of raising — losing one component's references is recoverable,
        losing the run is not.
        """
        known = state.get("budget_matches") or []
        covered = {match["component_id"] for match in known}
        seen = {(match["component_id"], match["reference_budget_id"]) for match in known}
        # The supervisor may send this agent back out for a second opinion. On
        # that pass a component that already has evidence is done — re-running
        # its query returns the same rows, and the reducer would APPEND them:
        # one real analogue counted twice reads as full coverage, confidence
        # rises with no new information, and a run that should have stopped for
        # a human clears the gate on evidence it already had.
        retry = _times_dispatched(state, "budget_searcher") > 1

        matches: list[BudgetMatch] = []
        errors: list[str] = []
        with logfire.span("agent.budget_searcher") as span:
            searched = 0
            for component in state.get("components") or []:
                if component["id"] in covered:
                    continue
                searched += 1
                # Different wording on the retry, and only where the first pass
                # found nothing: repeating the identical query is not a second
                # opinion. The display name and the kind of work are a genuinely
                # different description of the same component.
                query = (
                    f"{component['name']} — {component['category']}"
                    if retry
                    else component["search_query"]
                )
                try:
                    result = await _guarded(
                        "budget_searcher",
                        "search_budgets",
                        {"query": query, "filters": None},
                        state,
                        _call_search_budgets,
                    )
                    items = json.loads(result.output).get("items") or []
                except ActionDeniedError as exc:
                    log.warning(
                        "graph_search_denied", component=component["name"], reason=exc.reason
                    )
                    errors.append(f"search_budgets({component['name']}): denied — {exc.reason}")
                    continue
                except Exception as exc:  # noqa: BLE001 - degraded, see docstring
                    log.warning(
                        "graph_search_failed", component=component["name"], error=str(exc)[:200]
                    )
                    errors.append(f"search_budgets({component['name']}): {type(exc).__name__}")
                    continue
                for item in items:
                    key = (component["id"], str(item.get("budget_id")))
                    if not item.get("estimated_hours") or key in seen:
                        continue
                    seen.add(key)
                    matches.append(
                        BudgetMatch(
                            component_id=component["id"],
                            component=component["name"],
                            reference_budget_id=str(item.get("budget_id")),
                            amount=float(item.get("estimated_hours") or 0.0),
                            # Missing distance reads as "at the edge of
                            # usefulness", never as a perfect match: a backend
                            # that does not report closeness must not be
                            # rewarded with confidence.
                            distance=float(
                                item["distance"]
                                if item.get("distance") is not None
                                else _MAX_USEFUL_DISTANCE
                            ),
                        )
                    )
            span.set_attribute("components_searched", searched)
            span.set_attribute("matches", len(matches))
            span.set_attribute("failed_searches", len(errors))
            span.set_attribute("retry", retry)

        log.info("agent_done", agent="budget_searcher", matches=len(matches), retry=retry)
        # Both fields are accumulators: this returns only what THIS pass produced,
        # and only what was not already there.
        return Command(goto="supervisor", update={"budget_matches": matches, "errors": errors})

    @grants("calculate_estimate")
    async def estimate_generator(state: EstimationState) -> Command[Literal["supervisor"]]:
        """Components + their references → the costed estimate.

        The hours come from ``calculate_estimate`` — a median over the references
        plus a flat contingency, done in Python — and the model is asked only for
        the rationale behind each line. Splitting it this way is what makes the
        grant table load-bearing: the agent's one tool decides the numbers, and
        the model cannot overrule them.
        """
        components = state.get("components") or []
        by_component = _references_by_component(state)

        with logfire.span("agent.estimate_generator") as span:
            # The tool is keyed by "name", and the name we give it is our own id.
            # Joining on the prose the model wrote is the bug this graph already
            # paid for once; the id is the only key that survives a rewrite.
            try:
                priced = await _guarded(
                    "estimate_generator",
                    "calculate_estimate",
                    {
                        "components": [
                            {
                                "name": c["id"],
                                "reference_amounts": by_component.get(c["id"]) or [],
                            }
                            for c in components
                        ]
                    },
                    state,
                    _call_calculate_estimate,
                )
            except ActionDeniedError as exc:
                # A refused calculation is not a run that dies. Raising here
                # aborts the superstep, no status is ever written, and the
                # checkpoint parks the thread on this node forever: every retry
                # of that estimation_id fails identically and the human gate —
                # which exists for exactly this case, a meeting with nothing
                # concrete in it — is never reached. So the estimate degrades to
                # an unpriced one and the validator takes it from there.
                log.warning("graph_estimate_denied", reason=exc.reason)
                span.set_attribute("denied", True)
                return Command(
                    goto="supervisor",
                    update={
                        "estimate": _unpriced_estimate(components),
                        "errors": [f"calculate_estimate: denied — {exc.reason}"],
                    },
                )
            costed = json.loads(priced.output)
            hours_by_id = {line["name"]: line for line in costed["components"]}

            brief = "\n\n".join(
                f"id: {c['id']}\n"
                f"Component: {c['name']}\n"
                f"Kind of work: {c['category']}\n"
                f"Assigned hours: {hours_by_id.get(c['id'], {}).get('estimated_hours')}\n"
                f"Historical references (engineer-hours): "
                f"{by_component.get(c['id']) or 'none found'}"
                for c in components
            )
            narrative, meta = await structured_call(
                llm,
                system_prompt=NARRATIVE_SYSTEM,
                user_message=brief,
                model=estimate_model,
                response_model=EstimateNarrative,
                effort=reasoning_effort,
                # A reasoning model's thinking counts against max_tokens: the
                # 4000 default is spent before the JSON starts, and the call ends
                # truncated or timed out. Same lesson the S9 generator learned.
                max_tokens=estimate_max_tokens,
            )
            stamp_llm(span, meta)
            span.set_attribute("total_hours", costed["total_hours"])
            span.set_attribute(
                "unbudgeted", sum(1 for line in costed["components"] if line["unbudgeted"])
            )

        rationale_by_id = {
            _normalise_id(line.component_id): line.rationale for line in narrative.components
        }
        estimate = {
            "project": narrative.project,
            "components": [
                {
                    "component_id": c["id"],
                    "name": c["name"],
                    "estimated_hours": hours_by_id.get(c["id"], {}).get("estimated_hours", 0.0),
                    "grounded": not hours_by_id.get(c["id"], {}).get("unbudgeted", True),
                    "rationale": rationale_by_id.get(c["id"], ""),
                }
                for c in components
            ],
            "total_hours": costed["total_hours"],
            "notes": narrative.notes,
        }
        log.info("agent_done", agent="estimate_generator", total=costed["total_hours"])
        return Command(goto="supervisor", update={"estimate": estimate})

    @grants("validate_estimate")
    async def coherence_validator(state: EstimationState) -> Command[Literal["supervisor"]]:
        """The estimate's coherence verdict, and the confidence the gate fires on.

        ``confidence`` is computed here, in Python, from evidence that is already
        in the state: how much of the project is grounded, how much evidence each
        component got, and how close that evidence actually is. It is not asked
        of the model — a model scoring its own output rates it highly, and the
        human gate hangs off this number.
        """
        estimate = state.get("estimate") or {}
        lines = estimate.get("components") or []
        components = state.get("components") or []
        by_component = _references_by_component(state)

        with logfire.span("agent.coherence_validator") as span:
            try:
                reported = await _guarded(
                    "coherence_validator",
                    "validate_estimate",
                    {
                        "components": [
                            {
                                "name": _normalise_id(line.get("component_id")),
                                "estimated_hours": float(line.get("estimated_hours") or 0.0),
                                "reference_amounts": by_component.get(
                                    _normalise_id(line.get("component_id"))
                                )
                                or [],
                            }
                            for line in lines
                        ],
                        "total_hours": float(estimate.get("total_hours") or 0.0),
                    },
                    state,
                    _call_validate_estimate,
                )
                issues = list(json.loads(reported.output).get("issues") or [])
            except ActionDeniedError as exc:
                # A refused validation is not a validated estimate. It becomes a
                # concern, which is what drives the confidence down and the run
                # to a human — the only safe reading.
                issues = [f"validate_estimate: denied — {exc.reason}"]

            # Concerns the tool cannot see, because they are about the RUN rather
            # than about the arithmetic.
            concerns = list(issues)
            if not lines:
                concerns.append("the estimate has no components")
            if state.get("errors"):
                concerns.append(
                    f"the run degraded earlier ({len(state['errors'])} error(s)); "
                    "the evidence base is incomplete"
                )
            if lines and not any(line.get("grounded") for line in lines):
                concerns.append("no component is grounded in any historical reference")

            grounded_ratio = (
                sum(1 for line in lines if line.get("grounded")) / len(lines) if lines else 0.0
            )
            evidence_density = (
                sum(
                    min(
                        1.0,
                        len(by_component.get(c["id"]) or []) / _TARGET_REFERENCES_PER_COMPONENT,
                    )
                    for c in components
                )
                / len(components)
                if components
                else 0.0
            )
            distances = [m["distance"] for m in state.get("budget_matches") or []]
            proximity = (
                sum(_clamp(1 - d / _MAX_USEFUL_DISTANCE) for d in distances) / len(distances)
                if distances
                else 0.0
            )
            # The tool reports one issue per component with no reference, and
            # `grounded_ratio` already measures exactly those. Subtracting them
            # leaves the issues it knows and we do not: hours outside the
            # plausible band, and a total that is not the sum of its parts.
            # Counting the whole list instead penalised every unbudgeted
            # component TWICE — measured on a real run, the estimate scored 0.36
            # where the evidence said 0.66.
            ungrounded = sum(1 for line in lines if not line.get("grounded"))
            arithmetic_issues = max(0, len(issues) - ungrounded)
            # Weighted, not multiplied: a product collapses to zero on any single
            # weak term and would send every run to review. Each weight says how
            # much that signal is worth — grounding first, because a component
            # with no analogue is the failure that actually reaches the client.
            # The arithmetic penalty is steep because those issues are rare and
            # serious: with the hours coming from the tool they should never
            # appear at all, so one of them means something is wrong upstream.
            confidence = _clamp(
                0.5 * grounded_ratio
                + 0.3 * evidence_density
                + 0.2 * proximity
                - 0.2 * arithmetic_issues
            )

            result = ValidationResult(
                is_coherent=not concerns,
                confidence=round(confidence, 3),
                concerns=concerns,
                reasoning=(
                    f"{grounded_ratio:.0%} of the estimate is grounded in historical "
                    f"references, evidence density {evidence_density:.0%}, mean match "
                    f"proximity {proximity:.0%}, {ungrounded} component(s) with no "
                    f"precedent, {arithmetic_issues} arithmetic issue(s)."
                ),
            )
            span.set_attribute("confidence", result.confidence)
            span.set_attribute("concerns", len(result.concerns))
            span.set_attribute("is_coherent", result.is_coherent)

        log.info(
            "agent_done",
            agent="coherence_validator",
            confidence=result.confidence,
            concerns=len(result.concerns),
        )
        return Command(
            goto="supervisor",
            update={"validation": result.model_dump(), "confidence": result.confidence},
        )

    return {
        "requirements_extractor": requirements_extractor,
        "budget_searcher": budget_searcher,
        "estimate_generator": estimate_generator,
        "coherence_validator": coherence_validator,
    }


def build_finalize() -> Callable[[EstimationState], Awaitable[Command]]:
    """The one terminal, and the only writer of the final ``status``.

    One owner for ``status`` is deliberate. In Session 13 two nodes could write
    it and a thread that had already ended "validated" kept that value on a
    re-run whose guardrails had just failed. A field the contract is read from
    must never be inheritable, so this node always writes it — on every branch.
    """

    @grants()
    async def finalize(state: EstimationState) -> Command[Literal["__end__"]]:
        decision = state.get("human_decision") or {}
        validation = state.get("validation") or {}
        trail = state.get("routing_trail") or []

        # "The supervisor gave up" is a fact the supervisor produces, so it is
        # read from what it decided — the ONE route to this node that is not the
        # human gate — and not re-derived from the step counter. Deriving it
        # twice is how the first version got it wrong: the supervisor tests its
        # ceiling BEFORE incrementing, so exhaustion arrives here as
        # max_routing_steps + 1, while a run that used its last legal dispatch to
        # reach the gate arrives as exactly max_routing_steps. The same `>=` read
        # both as exhausted, and a human-approved estimate came back to the
        # business backend as a run that had run out of budget.
        if trail and trail[-1].get("next_agent") == "finalize":
            # A run that ran out is not a run that passed, and it must not read
            # as one — whatever a reviewer did or did not say about it.
            status = "routing_budget_exhausted"
        elif decision.get("action") == "reject":
            # A rejection reuses a value the business backend already handles
            # rather than inventing a second new one. The reason is preserved in
            # human_decision, which is the record that matters.
            status = "needs_review"
        elif decision.get("action") in ("approve", "adjust"):
            status = "validated"
        else:
            status = "validated" if validation.get("is_coherent") else "needs_review"

        with logfire.span("agent.finalize") as span:
            span.set_attribute("status", status)
            span.set_attribute("routing_steps", state.get("routing_steps", 0))
        log.info("agent_done", agent="finalize", status=status)
        return Command(goto=END, update={"status": status})

    return finalize
