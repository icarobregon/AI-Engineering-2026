"""The historical band: what projects of this shape have actually cost.

Two jobs, and the first one is the important one.

**It is the reviewer's frame of reference.** When the graph pauses, a number on
its own tells a human nothing. "142h" next to "comparable subsystems ran
110-260h" is a judgement they can make in ten seconds. That is why the band goes
in the interrupt payload.

**It is one of the three pause triggers.** An estimate outside the band is one
of the conditions the human gate fires on.

The band is SCALED by coverage, and that is the whole reason this trigger can
fire at all. ``calculate_estimate`` prices a component from its own references
(their median, plus a flat contingency), so any band built from those same
references contains the result by construction — a self-fulfilling check. But a
component with no comparable budget is priced at zero and still has to be built,
so the project's real cost is the band of the components we DID price, scaled up
by how much of the project they represent. An estimate that only prices three of
five components falls below that band, which is exactly the run a human should
see. When everything is covered the scale is 1.0 and the check goes quiet.
"""

from __future__ import annotations

from typing import Optional, TypedDict

from app.domain.graph.state import BudgetMatch, Component


class HistoricalBand(TypedDict):
    """The hours a project of this shape has historically cost."""

    low: float
    high: float
    # How many of the project's components had at least one comparable budget,
    # out of how many there are. The gap between them is what scales the band.
    covered_components: int
    total_components: int
    references: int


def historical_band(
    components: list[Component], budget_matches: list[BudgetMatch]
) -> Optional[HistoricalBand]:
    """The band, or ``None`` when no component has a comparable budget at all."""
    # Keyed by the id we assigned, never by the display name: two components the
    # classifier called the same thing would otherwise pool their references and
    # count as one priced component, understating the coverage the band scales by.
    by_component: dict[str, list[float]] = {}
    for match in budget_matches or []:
        by_component.setdefault(match["component_id"], []).append(float(match["amount"]))

    priced = {component_id: amounts for component_id, amounts in by_component.items() if amounts}
    if not priced:
        return None

    total_components = len(components) or len(priced)
    # Every priced component at its cheapest analogue, and at its priciest.
    low = sum(min(amounts) for amounts in priced.values())
    high = sum(max(amounts) for amounts in priced.values())
    scale = total_components / len(priced)

    return HistoricalBand(
        low=round(low * scale, 1),
        high=round(high * scale, 1),
        covered_components=len(priced),
        total_components=total_components,
        references=sum(len(amounts) for amounts in priced.values()),
    )


def is_outside_historical_band(
    estimate: Optional[dict],
    components: list[Component],
    budget_matches: list[BudgetMatch],
    *,
    tolerance: float,
) -> bool:
    """Whether the estimate's total falls outside the band, allowing ``tolerance``.

    No band means no verdict: a run with no historical evidence at all is caught
    by the no-precedent trigger, and reporting it as "out of range" too would
    just say the same thing twice to the reviewer.
    """
    if not estimate:
        return False
    band = historical_band(components, budget_matches)
    if band is None:
        return False

    total = float(estimate.get("total_hours") or 0.0)
    return total < band["low"] * (1 - tolerance) or total > band["high"] * (1 + tolerance)
