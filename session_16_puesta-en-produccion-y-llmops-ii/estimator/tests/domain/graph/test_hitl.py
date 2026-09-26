"""The trigger signal and the band, as pure functions.

Everything the gate does before it interrupts has to be pure and cheap, because
LangGraph re-runs the whole node body on every resume. That makes these
unit-testable without a graph, which is the point.
"""

from __future__ import annotations

import pytest

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




# --- el revisor pone precio componente a componente (S15) ----------------------


REVISABLE = {
    "project": "Lonja digital",
    "total_hours": 200.0,
    "components": [
        {"component_id": "c1", "name": "Backend", "estimated_hours": 120.0, "grounded": True},
        {"component_id": "c2", "name": "Visión", "estimated_hours": 0.0, "grounded": False},
        {"component_id": "c3", "name": "Avisos", "estimated_hours": 80.0, "grounded": True},
    ],
}


def test_the_total_is_the_sum_of_what_the_reviewer_priced():
    """El total no se manda nunca: se deriva. Es lo que hace imposible que la
    cifra de abajo y el desglose se contradigan."""
    revisado = apply_human_decision(
        REVISABLE, {"action": "approve", "component_hours": {"c2": 150.0}}
    )

    assert revisado["total_hours"] == 350.0
    assert revisado["original_total_hours"] == 200.0


def test_only_the_lines_the_reviewer_named_are_touched():
    revisado = apply_human_decision(
        REVISABLE, {"action": "approve", "component_hours": {"c2": 150.0}}
    )
    por_id = {c["component_id"]: c for c in revisado["components"]}

    assert por_id["c2"]["estimated_hours"] == 150.0
    assert por_id["c1"] == REVISABLE["components"][0]
    assert por_id["c3"] == REVISABLE["components"][2]


def test_the_system_figure_is_kept_only_where_it_actually_changed():
    # Un campo "original" en todas las filas obliga a la pantalla a comparar para
    # saber si hubo revisión, y acaba tachando números idénticos.
    revisado = apply_human_decision(
        REVISABLE,
        {"action": "approve", "component_hours": {"c1": 120.0, "c2": 150.0}},
    )
    por_id = {c["component_id"]: c for c in revisado["components"]}

    assert "original_estimated_hours" not in por_id["c1"]
    assert por_id["c2"]["original_estimated_hours"] == 0.0


def test_an_id_that_is_not_in_the_estimate_is_ignored():
    # Nunca se crea una línea que nadie estimó ni respaldó con nada.
    revisado = apply_human_decision(
        REVISABLE, {"action": "approve", "component_hours": {"c9": 999.0}}
    )

    assert len(revisado["components"]) == 3
    assert revisado["total_hours"] == 200.0


def test_a_rejection_also_records_what_was_considered():
    """Un rechazo es evidencia de lo que se valoró antes de decir que no, y esa
    distancia es con lo que se calibra el umbral."""
    revisado = apply_human_decision(
        REVISABLE, {"action": "reject", "component_hours": {"c2": 150.0}}
    )

    assert revisado["total_hours"] == 350.0
    assert revisado["components"][1]["estimated_hours"] == 150.0


def test_grounding_survives_the_reviewers_pen():
    # `grounded` habla de si hay evidencia histórica, no de si hay un número: un
    # componente que un humano puso a mano sigue sin precedente, y el cliente
    # tiene que poder verlo en el documento final.
    revisado = apply_human_decision(
        REVISABLE, {"action": "approve", "component_hours": {"c2": 150.0}}
    )

    assert revisado["components"][1]["grounded"] is False


def test_a_decision_with_no_hours_leaves_the_estimate_alone():
    # Una aprobación a secas no toca ningún número: el sistema ya dijo lo suyo.
    assert apply_human_decision(REVISABLE, {"action": "approve"}) == REVISABLE
    assert apply_human_decision(REVISABLE, {"action": "approve", "component_hours": {}}) == REVISABLE


def test_only_two_actions_are_accepted_at_the_door():
    """El total suelto de las S13-S14 ya no es una acción posible.

    Se comprueba en el ESQUEMA y no en la función: `apply_human_decision` no
    mira la acción desde la S15 —aplica lo que llegue, apruebe o rechace— así
    que el único sitio donde «adjust» puede rebotar es la validación de entrada.
    """
    from pydantic import ValidationError

    from app.domain.schemas.graph_estimation import HumanDecision

    assert HumanDecision(action="approve").action == "approve"
    assert HumanDecision(action="reject").action == "reject"
    with pytest.raises(ValidationError):
        HumanDecision(action="adjust")
