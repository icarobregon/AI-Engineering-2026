"""The only thing the supervisor gets to see.

A compact projection of the state, so one routing decision costs the same
whether the meeting ran ten minutes or two hours. Passing the history instead
would make the router the most expensive node in the graph and grow its bill
with every iteration — the failure this projection exists to avoid.

It reports **who has already acted**, not **which output fields are non-empty**.
The difference is not cosmetic: a specialist that legitimately produced nothing
(a search with no comparable budget in the corpus) looks identical to one that
never ran, so a supervisor reading output fields dispatches it again, and again,
until the routing budget dies. Reading the trail, "searched and found nothing"
is a fact the run can move on from — which is exactly the case the human gate
was built for.
"""

from __future__ import annotations

from app.domain.graph.state import EstimationState


def agents_that_acted(state: EstimationState) -> set[str]:
    """The specialists the supervisor has already dispatched, from the trail."""
    return {entry.get("next_agent", "") for entry in state.get("routing_trail") or []}


def build_state_digest(state: EstimationState) -> str:
    """Compact projection of the state. This is all the supervisor gets to see."""
    acted = agents_that_acted(state)
    lines = [
        f"requirements_extracted: {len(state.get('requirements') or [])} items",
        f"components_classified: {len(state.get('components') or [])}",
        f"budget_matches_found: {len(state.get('budget_matches') or [])}",
        f"estimate_produced: {state.get('estimate') is not None}",
        f"validation_done: {state.get('validation') is not None}",
        f"confidence: {state.get('confidence')}",
        f"errors_recorded: {len(state.get('errors') or [])}",
        f"agents_already_run: {sorted(acted) or 'none'}",
        f"routing_steps_so_far: {state.get('routing_steps', 0)}",
    ]
    return "\n".join(lines)
