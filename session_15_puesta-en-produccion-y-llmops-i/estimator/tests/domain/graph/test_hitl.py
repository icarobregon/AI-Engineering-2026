"""The trigger signal and the band, as pure functions.

Everything the gate does before it interrupts has to be pure and cheap, because
LangGraph re-runs the whole node body on every resume. That makes these
unit-testable without a graph, which is the point.
"""

from __future__ import annotations

from app.domain.graph.band import historical_band, is_outside_historical_band
from app.domain.graph.hitl import (
    apply_human_decision,
    build_review_reason,
    requires_human_review,
)

COMPONENTS = [
    {"id": "c1", "name": "Backend", "category": "backend", "search_query": "q1"},
    {"id": "c2", "name": "App", "category": "mobile", "search_query": "q2"},
]


_IDS = {"Backend": "c1", "App": "c2"}


def _match(component: str, amount: float, distance: float = 0.2) -> dict:
    return {
        "component_id": _IDS[component],
        "component": component,
        "reference_budget_id": f"B/{component}/{amount}",
        "amount": amount,
        "distance": distance,
    }


def _state(**overrides) -> dict:
    base = {
        "components": COMPONENTS,
        "budget_matches": [
            _match("Backend", 100.0),
            _match("Backend", 140.0),
            _match("App", 80.0),
            _match("App", 120.0),
        ],
        "estimate": {"total_hours": 250.0},
        "confidence": 0.9,
        "routing_trail": [{"next_agent": "budget_searcher", "reason": "x"}],
    }
    return base | overrides


# --- the band ----------------------------------------------------------------


def test_the_band_is_every_component_at_its_cheapest_and_at_its_priciest():
    band = historical_band(COMPONENTS, _state()["budget_matches"])

    assert band["low"] == 180.0  # 100 + 80
    assert band["high"] == 260.0  # 140 + 120
    assert band["covered_components"] == 2
    assert band["references"] == 4


def test_the_band_scales_up_for_the_components_nothing_was_found_for():
    """This scaling is the only reason the trigger can fire at all.

    ``calculate_estimate`` prices a component from its own references, so a band
    built from those same references contains the result by construction. But a
    component with no analogue is priced at zero and still has to be built, so
    the project's real cost is the band of what we DID price, scaled by how much
    of the project that is.
    """
    matches = [_match("Backend", 100.0), _match("Backend", 140.0)]

    band = historical_band(COMPONENTS, matches)

    assert band["covered_components"] == 1
    assert band["total_components"] == 2
    assert band["low"] == 200.0 and band["high"] == 280.0


def test_no_evidence_means_no_band_and_therefore_no_verdict():
    assert historical_band(COMPONENTS, []) is None
    # Saying "out of range" about a run with no range would just repeat what the
    # no-precedent trigger already says.
    assert not is_outside_historical_band({"total_hours": 10.0}, COMPONENTS, [], tolerance=0.25)


def test_an_estimate_that_prices_half_the_project_falls_below_the_band():
    matches = [_match("Backend", 100.0), _match("Backend", 140.0)]

    assert is_outside_historical_band({"total_hours": 138.0}, COMPONENTS, matches, tolerance=0.25)


def test_a_fully_covered_estimate_sits_inside_its_own_band():
    state = _state()

    assert not is_outside_historical_band(
        state["estimate"], COMPONENTS, state["budget_matches"], tolerance=0.25
    )


# --- the trigger --------------------------------------------------------------


def test_a_confident_well_covered_estimate_does_not_need_a_human():
    assert requires_human_review(_state(), confidence_threshold=0.7, band_tolerance=0.25) == []


def test_low_confidence_fires():
    reasons = requires_human_review(
        _state(confidence=0.31), confidence_threshold=0.7, band_tolerance=0.25
    )

    assert any("0.31 is below" in reason for reason in reasons)


def test_an_unknown_confidence_is_treated_as_low():
    reasons = requires_human_review(
        _state(confidence=None), confidence_threshold=0.7, band_tolerance=0.25
    )

    assert any("unknown" in reason for reason in reasons)


def test_no_precedent_fires_only_once_the_searcher_has_actually_run():
    searched = _state(budget_matches=[], estimate={"total_hours": 0.0})
    not_yet = searched | {"routing_trail": []}

    assert any(
        "no comparable budget" in reason
        for reason in requires_human_review(searched, confidence_threshold=0.7, band_tolerance=0.25)
    )
    assert not any(
        "no comparable budget" in reason
        for reason in requires_human_review(not_yet, confidence_threshold=0.7, band_tolerance=0.25)
    )


def test_the_reason_summarises_without_hiding_how_many_triggers_fired():
    assert build_review_reason([]) == "No trigger fired."
    assert build_review_reason(["confidence is low"]) == "Confidence is low"
    assert "2 more concern(s)" in build_review_reason(["a", "b", "c"])


# --- the decision --------------------------------------------------------------


def test_an_approval_changes_nothing_about_the_numbers():
    estimate = {"total_hours": 250.0}

    assert apply_human_decision(estimate, {"action": "approve"}) == estimate


def test_an_adjustment_replaces_the_total_and_keeps_what_the_system_said():
    adjusted = apply_human_decision(
        {"total_hours": 250.0}, {"action": "adjust", "adjusted_hours": 180}
    )

    assert adjusted["total_hours"] == 180.0
    # Both numbers are evidence: the gap between them is how the threshold gets
    # calibrated against what reviewers actually decide.
    assert adjusted["original_total_hours"] == 250.0


def test_an_adjustment_with_no_number_is_not_an_adjustment():
    estimate = {"total_hours": 250.0}

    assert apply_human_decision(estimate, {"action": "adjust"}) == estimate
