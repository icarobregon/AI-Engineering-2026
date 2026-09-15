"""The five nodes of the estimation graph (plus the review terminal).

Each node is a pure function of the state: it reads what it needs, does one
thing, and returns ONLY the fields it changed. It never decides who runs next —
that is the edges' job, and moving it into a node is how a graph quietly turns
back into the tangled loop it replaced.

**Why a factory instead of module-level functions.** The nodes need the LLM
wrapper and the retrieval backend, and ``app/domain/`` may not import
``app.dependencies`` (ARCHITECTURE.md §3: the composition root is imported by
``api/`` and the tests, never by a layer). So the collaborators are bound at
build time and the nodes close over them. They stay pure functions of the state
— which is what the graph and the tests care about — and the wiring stays in the
one place that is allowed to know about wiring.

Spans: every node opens ``node: <name>`` and stamps what the live session will
want to read — how many items it produced, and for the LLM nodes the model, the
tokens and the cost. With no Logfire token configured the spans still run, they
just are not exported.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

import logfire
import structlog

from app.domain.graph.schemas import ComponentList, DraftEstimate, RequirementList
from app.domain.graph.state import BudgetMatch, Component, EstimationState

log = structlog.get_logger()


def _normalise_id(raw: Any) -> str:
    """Read a component id the way the model may have written it.

    A real run returned "[c1]" because the prompt had shown the id inside
    brackets. The identity is ours and it is unambiguous; brackets and stray
    whitespace around it are punctuation, not a different component, and
    rejecting the whole line over them would flag a correct estimate.
    """
    return str(raw or "").strip().strip("[]").strip()


# A component costed outside this band is reported, not silently accepted.
_MIN_PLAUSIBLE_HOURS = 8.0
_MAX_PLAUSIBLE_HOURS = 4000.0
# Rounding drift we tolerate between the total and the sum of its parts.
_TOTAL_TOLERANCE = 0.5

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

ESTIMATE_SYSTEM = """\
You turn historical evidence into an effort estimate in engineer-hours.

You are given the project's components and, for each, the hours that comparable \
subsystems of past projects actually took. Those numbers are your only source: \
never invent hours, and never adjust a number because it feels low or high.

Each component is given with an `id:` line. Copy that value into \
`component_id` — just the value, like `c1` — one line per component and no more: \
it is how your estimate is matched back to its evidence.

For each component, estimate from its references and say in one line which ones \
back it. A component with no references at all gets `grounded: false`, zero \
hours, and a plain statement of the gap — an unbudgeted component is a fact the \
reader needs, not a hole to fill. References from another sector still count as \
evidence; use them and note the mismatch.

`total_hours` is the sum of the component hours. Write the prose in the language \
of the transcript.
"""


def build_nodes(
    *,
    llm: Any,
    search_backend: Callable[..., Awaitable[list[dict]]],
    fast_model: str,
    estimate_model: str,
    reasoning_effort: str = "medium",
    search_top_k: int = 5,
    estimate_max_tokens: int = 16000,
) -> dict[str, Callable[[EstimationState], Awaitable[dict]]]:
    """Bind the collaborators and return the graph's nodes by name."""

    async def _structured(
        system_prompt: str,
        user_message: str,
        model: str,
        response_model,
        *,
        effort=None,
        max_tokens: int | None = None,
    ):
        """Call the project's LLM wrapper off the event loop.

        ``complete_structured`` is synchronous (Instructor + LiteLLM); the graph
        is async, so it goes to a thread rather than blocking the loop that the
        retrieval and the checkpointer share.
        """
        return await asyncio.to_thread(
            llm.complete_structured,
            system_prompt=system_prompt,
            user_message=user_message,
            response_model=response_model,
            model_override=model,
            reasoning_effort=effort,
            **({"max_tokens": max_tokens} if max_tokens else {}),
        )

    def _stamp_llm(span, meta: dict) -> None:
        """Put on the span what the call cost, when it reported it.

        Only keys actually present are stamped: an attribute that is always None
        reads like an instrumented number and is worse than an absent one,
        because a dashboard will happily sum it to zero. The first version
        stamped cost and tokens unconditionally — and complete_structured
        reports neither, so every node span carried two null numbers.
        """
        for key, value in (
            ("model", meta.get("model")),
            ("latency_ms", meta.get("latency_ms")),
            ("llm_cost_usd", meta.get("cost_usd")),
            ("total_tokens", (meta.get("usage") or {}).get("total_tokens")),
        ):
            if value is not None:
                span.set_attribute(key, value)

    async def extract_requirements(state: EstimationState) -> dict:
        """Transcript → the list of things that must be built."""
        with logfire.span("node: extract_requirements") as span:
            result, meta = await _structured(
                EXTRACT_SYSTEM, state["transcript"], fast_model, RequirementList
            )
            _stamp_llm(span, meta)
            span.set_attribute("requirements", len(result.requirements))
        log.info("graph_node_done", node="extract_requirements", count=len(result.requirements))
        return {"requirements": result.requirements}

    async def classify_components(state: EstimationState) -> dict:
        """Requirements → the components the project will be estimated by."""
        with logfire.span("node: classify_components") as span:
            listing = "\n".join(f"- {r}" for r in state["requirements"])
            result, meta = await _structured(CLASSIFY_SYSTEM, listing, fast_model, ComponentList)
            _stamp_llm(span, meta)
            span.set_attribute("components", len(result.components))
        # The id is ours, assigned by position. Everything downstream joins on it.
        components: list[Component] = [
            {
                "id": f"c{index}",
                "name": c.name,
                "category": c.category,
                "search_query": c.search_query,
            }
            for index, c in enumerate(result.components, start=1)
        ]
        log.info("graph_node_done", node="classify_components", count=len(components))
        return {"components": components}

    async def search_budgets(state: EstimationState) -> dict:
        """Each component → the historical subsystems comparable to it.

        Sequential on purpose: the pre-work measures what one-after-another
        costs, and the live session turns this loop into a fan-out. A component
        whose search fails degrades into ``errors`` instead of raising — losing
        one component's references is recoverable, losing the run is not.
        """
        matches: list[BudgetMatch] = []
        errors: list[str] = []
        with logfire.span("node: search_budgets") as span:
            for component in state["components"]:
                try:
                    items = await search_backend(component["search_query"], top_k=search_top_k)
                except Exception as exc:  # noqa: BLE001 - degraded, see docstring
                    log.warning(
                        "graph_search_failed", component=component["name"], error=str(exc)[:200]
                    )
                    errors.append(f"search_budgets({component['name']}): {type(exc).__name__}")
                    continue
                matches.extend(
                    BudgetMatch(
                        component=component["name"],
                        reference_budget_id=str(item.get("budget_id")),
                        amount=float(item.get("estimated_hours") or 0.0),
                    )
                    for item in items
                    if item.get("estimated_hours")
                )
            span.set_attribute("components_searched", len(state["components"]))
            span.set_attribute("matches", len(matches))
            span.set_attribute("failed_searches", len(errors))
        log.info("graph_node_done", node="search_budgets", matches=len(matches))
        # Both fields are accumulators: this returns only what THIS node produced.
        return {"budget_matches": matches, "errors": errors}

    async def generate_estimate(state: EstimationState) -> dict:
        """Components + their references → the consolidated estimate."""
        with logfire.span("node: generate_estimate") as span:
            by_component: dict[str, list[float]] = {}
            for match in state["budget_matches"]:
                by_component.setdefault(match["component"], []).append(match["amount"])
            brief = "\n\n".join(
                f"id: {c['id']}\n"
                f"Component: {c['name']}\n"
                f"Kind of work: {c['category']}\n"
                f"Historical references (engineer-hours): "
                f"{by_component.get(c['name']) or 'none found'}"
                for c in state["components"]
            )
            result, meta = await _structured(
                ESTIMATE_SYSTEM,
                brief,
                estimate_model,
                DraftEstimate,
                effort=reasoning_effort,
                # A reasoning model's thinking counts against max_tokens: the
                # 4000 default is spent before the JSON starts, and the call ends
                # truncated or timed out. Same lesson the S9 generator learned.
                max_tokens=estimate_max_tokens,
            )
            _stamp_llm(span, meta)
            span.set_attribute("total_hours", result.total_hours)
        log.info("graph_node_done", node="generate_estimate", total=result.total_hours)
        return {"estimate": result.model_dump()}

    async def validate_and_consolidate(state: EstimationState) -> dict:
        """Deterministic guardrails over the estimate. No LLM here.

        It ALWAYS writes ``status`` — passing or failing. Writing it only on
        success looked tidier and was a hole: ``status`` is a last-write-wins
        channel the checkpointer restores, so a thread that had already ended
        "validated" kept that value, the edge read it, and a run whose guardrails
        had just failed shipped as validated. A field the edges route on must
        never be inheritable.
        """
        with logfire.span("node: validate_and_consolidate") as span:
            estimate = state.get("estimate") or {}
            components = estimate.get("components") or []
            backed = {m["component"] for m in state["budget_matches"]}
            # Join on the id we assigned, never on the name the model wrote.
            by_id = {c["id"]: c for c in state["components"]}
            issues: list[str] = []

            if not components:
                issues.append("validate: the estimate has no components")

            for component in components:
                component_id = _normalise_id(component.get("component_id"))
                known = by_id.get(component_id)
                name = (known or {}).get("name") or component.get("name", "?")
                hours = float(component.get("estimated_hours") or 0.0)
                if known is None:
                    issues.append(
                        f"validate: {name} refers to component id {component_id!r}, "
                        "which is not one of the components that were classified"
                    )
                elif component.get("grounded") and name not in backed:
                    issues.append(f"validate: {name} claims grounding with no reference behind it")
                if hours and not (_MIN_PLAUSIBLE_HOURS <= hours <= _MAX_PLAUSIBLE_HOURS):
                    issues.append(
                        f"validate: {name} at {hours}h is outside the plausible band "
                        f"({_MIN_PLAUSIBLE_HOURS}-{_MAX_PLAUSIBLE_HOURS}h)"
                    )

                if not component.get("grounded") and hours:
                    # The inverse of the check above, and the one that matters
                    # more: a line that admits it has no evidence must not carry
                    # a number, or the total quietly includes invented work.
                    issues.append(f"validate: {name} is not grounded but carries {hours}h")

            if state.get("errors"):
                # Something degraded before we got here (a search that failed),
                # so the evidence base is incomplete by construction.
                issues.append(
                    f"validate: the run degraded earlier ({len(state['errors'])} error(s)); "
                    "the evidence base is incomplete"
                )
            if components and not any(c.get("grounded") for c in components):
                issues.append("validate: no component is grounded in any historical reference")

            total = float(estimate.get("total_hours") or 0.0)
            recomputed = round(sum(float(c.get("estimated_hours") or 0.0) for c in components), 1)
            if abs(total - recomputed) > _TOTAL_TOLERANCE:
                issues.append(
                    f"validate: total {total}h does not match the sum of its parts ({recomputed}h)"
                )

            span.set_attribute("issues", len(issues))
            span.set_attribute("passed", not issues)

        log.info("graph_node_done", node="validate_and_consolidate", issues=len(issues))
        # Written on both branches: None is what stops a previous run's
        # "validated" from being inherited on a reused thread.
        return {"status": None if issues else "validated", "errors": issues}

    async def flag_for_review(state: EstimationState) -> dict:
        """Terminal for an estimate a human has to look at before it ships."""
        with logfire.span("node: flag_for_review") as span:
            span.set_attribute("errors", len(state.get("errors") or []))
        log.info("graph_node_done", node="flag_for_review", errors=len(state.get("errors") or []))
        return {"status": "needs_review"}

    return {
        "extract_requirements": extract_requirements,
        "classify_components": classify_components,
        "search_budgets": search_budgets,
        "generate_estimate": generate_estimate,
        "validate_and_consolidate": validate_and_consolidate,
        "flag_for_review": flag_for_review,
    }
