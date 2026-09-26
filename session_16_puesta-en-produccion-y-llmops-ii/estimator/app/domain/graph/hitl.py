"""The human gate: where the graph stops and asks.

The pause is not a new mechanism. It is the Session 13 checkpointer, used for
what it was always able to do: ``interrupt()`` raises, LangGraph persists the
state it already had, and the process is free to go away entirely. Days later a
different process resumes the same ``thread_id`` and the run continues from
where it stopped.

**This node does nothing but interrupt.** On resume LangGraph re-runs the node
body from its first line — measured: two interrupts in a node means the body
executes three times — and it DISCARDS whatever the interrupted pass wrote. So
anything expensive above the ``interrupt()`` call is paid twice and anything
written above it is lost. The trigger read, the payload and the decision are all
pure functions of state that the specialists already computed.

**The span opens after the interrupt, not around it.** ``interrupt()`` works by
raising, so a span wrapping it is closed by an exception and exported with
``status=ERROR``. A run pausing for a human is the system working; it must not
arrive in the dashboard looking like a failure.

**One gate, at the point that matters.** A failed tool or a timeout is an error
and gets a retry or a fallback; a human is asked for judgement, not for manual
retries. Ten gates spread through the graph is how a reviewer learns to approve
without reading.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Literal

import logfire
import structlog
from langgraph.types import Command, interrupt

from app.domain.graph.band import historical_band, is_outside_historical_band
from app.domain.graph.digest import agents_that_acted
from app.domain.graph.state import EstimationState
from app.domain.security.grants import grants

log = structlog.get_logger()


def requires_human_review(
    state: EstimationState, *, confidence_threshold: float, band_tolerance: float
) -> list[str]:
    """The trigger signal, as the list of reasons that fired. Empty means pass.

    A boolean would be enough to route on and useless to the person who has to
    decide: "confidence 0.31" and "three components have no precedent in the
    corpus" are the same boolean and very different briefings.
    """
    reasons: list[str] = []

    confidence = state.get("confidence")
    if confidence is None or confidence < confidence_threshold:
        reasons.append(
            f"confidence {confidence if confidence is not None else 'unknown'} is below "
            f"the {confidence_threshold} threshold"
        )

    components = state.get("components") or []
    matches = state.get("budget_matches") or []
    if is_outside_historical_band(
        state.get("estimate"), components, matches, tolerance=band_tolerance
    ):
        band = historical_band(components, matches)
        reasons.append(
            f"the estimate falls outside what comparable work has cost "
            f"({band['low']}-{band['high']}h)"
        )

    # "The searcher ran and came back with nothing" — not "we have not searched
    # yet", which is a different state and the supervisor's business.
    if "budget_searcher" in agents_that_acted(state) and not matches:
        reasons.append("no comparable budget was found for any component of this project")

    return reasons


def build_review_reason(reasons: list[str]) -> str:
    """The one-line headline of why this estimate is in front of a person."""
    if not reasons:
        return "No trigger fired."
    if len(reasons) == 1:
        return reasons[0].capitalize()
    return f"{reasons[0].capitalize()}, and {len(reasons) - 1} more concern(s)."


def apply_human_decision(estimate: dict | None, decision: dict) -> dict | None:
    """Fold the reviewer's decision into the estimate.

    Since Session 15 the reviewer prices COMPONENT BY COMPONENT and the total is
    their sum, so the total is never sent and never trusted: deriving it here is
    what makes the bottom line and the breakdown incapable of disagreeing.

    What the system produced is kept beside what the person decided, per line and
    in total. Both are evidence — the gap between them is what the confidence
    threshold gets calibrated against — and the proposal reads this same estimate,
    so the document that reaches the client carries the approved numbers and can
    say which ones a human changed.

    Applied on approve AND on reject. A rejection is also a record of what was
    considered before saying no.

    The bare-total ``adjust`` of Sessions 13-14 is gone with it. It was only ever
    reachable from a live request, and no client can send that action any more —
    checkpoints written back then keep their own shape in the state and are never
    replayed through here.
    """
    if not estimate:
        return estimate

    hours = decision.get("component_hours") or {}
    if not hours:
        return estimate

    lines = []
    for line in estimate.get("components") or []:
        component_id = line.get("component_id")
        # Sólo se tocan las líneas que el revisor nombró, y por ID: un id que no
        # está en la estimación se ignora en lugar de crear una línea que nadie
        # estimó ni respaldó con nada.
        if component_id not in hours:
            lines.append(line)
            continue
        decided = float(hours[component_id])
        previous = line.get("estimated_hours")
        lines.append(
            {
                **line,
                "estimated_hours": decided,
                # Sólo cuando de verdad cambia: un campo "original" presente en
                # todas las filas obliga a la pantalla a comparar para saber si
                # hubo revisión, y acaba tachando números iguales.
                **(
                    {"original_estimated_hours": previous}
                    if previous is not None and float(previous) != decided
                    else {}
                ),
            }
        )

    return {
        **estimate,
        "components": lines,
        "total_hours": round(sum(float(line.get("estimated_hours") or 0.0) for line in lines), 1),
        "original_total_hours": estimate.get("total_hours"),
    }


def build_human_review_gate(
    *, confidence_threshold: float, band_tolerance: float
) -> Callable[[EstimationState], Awaitable[Command]]:
    """Bind the thresholds and return the gate node."""

    @grants()
    async def human_review_gate(state: EstimationState) -> Command[Literal["finalize"]]:
        reasons = requires_human_review(
            state,
            confidence_threshold=confidence_threshold,
            band_tolerance=band_tolerance,
        )
        if not reasons:
            with logfire.span("agent.human_review_gate") as span:
                span.set_attribute("paused", False)
            log.info("human_review_skipped", confidence=state.get("confidence"))
            return Command(goto="finalize")

        components = state.get("components") or []
        matches = state.get("budget_matches") or []
        # The payload is the reviewer's interface, not a log line: everything
        # they need to make the call, and nothing they would have to go and look
        # up somewhere else.
        decision = interrupt(
            {
                "estimation_id": state.get("estimation_id"),
                "reason": build_review_reason(reasons),
                "triggers": reasons,
                "estimate": state.get("estimate"),
                "confidence": state.get("confidence"),
                "concerns": (state.get("validation") or {}).get("concerns") or [],
                "historical_band": historical_band(components, matches),
                "budget_matches": matches,
            }
        )

        # Only reached on the resume pass: interrupt() returns the value the
        # reviewer sent, and the whole body above has just run a second time.
        with logfire.span("agent.human_review_gate") as span:
            span.set_attribute("paused", True)
            span.set_attribute("action", (decision or {}).get("action"))
        log.info(
            "human_review_resumed",
            estimation_id=state.get("estimation_id"),
            action=(decision or {}).get("action"),
            reviewer_id=(decision or {}).get("reviewer_id"),
        )
        return Command(
            goto="finalize",
            update={
                "human_decision": decision,
                "estimate": apply_human_decision(state.get("estimate"), decision or {}),
            },
        )

    return human_review_gate
