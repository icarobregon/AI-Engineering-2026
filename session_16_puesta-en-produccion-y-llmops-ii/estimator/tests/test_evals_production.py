"""The scoring of the Session 16 harness, tested without spending a token.

The harness calls the real model; its ARITHMETIC must not. Everything here runs
on canned response bodies, which is what lets these tests live in CI next to the
rest of the suite while the evaluation itself stays a deliberate, paid exercise.

The cases below are the traps the harness is built around, and each one was a
real finding before it was a test: a null total that is not an abstention, an
answer in the wrong unit, an estimate that only exists inside a human-review
payload, and a citation pointing at a document the corpus never had.
"""

from __future__ import annotations

import json

import pytest

from evals.production.run_eval import (
    _graph_reading,
    _percentile,
    _rag_reading,
    _source_verdict,
    evaluate_case,
    load_golden_set,
    summarise,
)

CORPUS = {"TASK-2024-0012": "ecommerce", "BUD-2024-005": "ecommerce", "TASK-2022-0036": "healthcare"}

ESTIMATION_CASE = {
    "id": "case-x",
    "difficulty": "easy",
    "sector": "ecommerce",
    "expected_hours": 680,
    "acceptable_range_hours": [450, 950],
    "expect_abstention": False,
    "expected_source_sectors": ["ecommerce"],
}

ABSTENTION_CASE = {
    "id": "case-z",
    "difficulty": "abstention",
    "sector": None,
    "expected_hours": None,
    "acceptable_range_hours": None,
    "expect_abstention": True,
    "expected_source_sectors": [],
}


def _rag_body(days, confidence="medium", document_ids=()):
    return {
        "total_engineer_days": days,
        "confidence": confidence,
        "modules": [
            {
                "name": "Checkout",
                "tasks": [
                    {
                        "name": "Cart",
                        "grounded": True,
                        "engineer_days": days,
                        "sources": [{"chunk_id": 1, "document_id": d, "evidence": "..."}
                                    for d in document_ids],
                    }
                ],
            }
        ],
    }


def _result(body, status=200, latency_ms=1000.0):
    return {"status": status, "body": body, "latency_ms": latency_ms}


# --------------------------------------------------------------------------- #
# The unit
# --------------------------------------------------------------------------- #


def test_rag_days_are_converted_to_the_golden_sets_hours() -> None:
    reading = _rag_reading(_rag_body(85), hours_per_day=8)
    assert reading["predicted_hours"] == 680
    assert reading["raw_value"] == 85 and reading["raw_unit"] == "engineer_days"


def test_an_answer_in_the_wrong_unit_reads_as_a_clean_factor() -> None:
    """The failure this whole harness was built to make legible.

    A model that copies the corpus's hours into a field named days answers 680
    where 85 was meant. Graded blind that is just "very high"; with the ratio it
    is an 8, which points straight at the prompt line that never states how many
    hours a day has.
    """
    verdict = evaluate_case(
        ESTIMATION_CASE, _result(_rag_body(680)), target="rag", hours_per_day=8, corpus=CORPUS
    )
    assert verdict["passed"] is False
    assert verdict["predicted_hours"] == 5440
    assert verdict["ratio_to_expected"] == 8.0


# --------------------------------------------------------------------------- #
# Range and abstention
# --------------------------------------------------------------------------- #


def test_a_figure_inside_the_band_passes_even_if_it_is_not_the_expected_one() -> None:
    verdict = evaluate_case(
        ESTIMATION_CASE, _result(_rag_body(60)), target="rag", hours_per_day=8, corpus=CORPUS
    )
    assert verdict["passed"] is True
    assert verdict["abs_error_hours"] == 200  # 480 h against the 680 h expected


def test_the_abstention_case_passes_only_on_the_declared_verdict() -> None:
    verdict = evaluate_case(
        ABSTENTION_CASE,
        _result(_rag_body(None, confidence="insufficient")),
        target="rag",
        hours_per_day=8,
        corpus=CORPUS,
    )
    assert verdict["passed"] is True


def test_a_null_total_is_not_by_itself_an_abstention() -> None:
    """``check_coherence`` only constrains the insufficient case.

    A run whose grounded lines carry no days yields a null total with confidence
    'medium' — legal, and not the system saying it does not know. Reading the
    null as an abstention would score that as a safety success.
    """
    reading = _rag_reading(_rag_body(None, confidence="medium"), hours_per_day=8)
    assert reading["predicted_hours"] is None
    assert reading["abstained"] is False

    verdict = evaluate_case(
        ABSTENTION_CASE,
        _result(_rag_body(None, confidence="medium")),
        target="rag",
        hours_per_day=8,
        corpus=CORPUS,
    )
    assert verdict["passed"] is False


def test_an_abstention_case_that_answers_with_aplomb_fails() -> None:
    verdict = evaluate_case(
        ABSTENTION_CASE,
        _result(_rag_body(90, confidence="high")),
        target="rag",
        hours_per_day=8,
        corpus=CORPUS,
    )
    assert verdict["passed"] is False
    assert "720" in verdict["detail"]


# --------------------------------------------------------------------------- #
# The graph target
# --------------------------------------------------------------------------- #


def test_a_paused_run_still_yields_its_figure() -> None:
    """A run stopped in front of a person carries the estimate the reviewer sees.

    Reading only ``estimate`` would score every escalated run as "no figure" and
    report the human gate as a failure of the system it protects.
    """
    body = {
        "estimate": None,
        "status": "awaiting_human_review",
        "review_payload": {
            "estimate": {
                "total_hours": 700.0,
                "components": [{"component_id": "C1", "grounded": True}],
            }
        },
    }
    reading = _graph_reading(body, {"budget_matches": [{"reference_budget_id": "TASK-2024-0012/Checkout"}]})
    assert reading["predicted_hours"] == 700.0
    assert reading["escalated"] is True
    assert reading["documents"] == ["TASK-2024-0012"]


def test_escalation_counts_as_the_graphs_way_of_not_knowing() -> None:
    body = {"estimate": None, "status": "awaiting_human_review", "review_payload": {}}
    verdict = evaluate_case(
        ABSTENTION_CASE, _result(body), target="graph", hours_per_day=8, corpus=CORPUS
    )
    assert verdict["passed"] is True


def test_an_estimate_with_nothing_grounded_is_not_an_answer() -> None:
    body = {
        "estimate": {"total_hours": 0.0, "components": [{"component_id": "C1", "grounded": False}]},
        "status": "needs_review",
    }
    reading = _graph_reading(body, {})
    assert reading["abstained"] is True
    assert reading["predicted_hours"] is None


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


def test_a_citation_outside_the_corpus_is_counted_as_fabricated() -> None:
    verdict = _source_verdict(
        ["TASK-2024-0012", "TASK-9999-0001", "TASK-2024-0012"], ESTIMATION_CASE, CORPUS
    )
    assert verdict["cited"] == 2
    assert verdict["fabricated"] == ["TASK-9999-0001"]
    assert verdict["sector_match_rate"] == 0.5


def test_sources_are_split_by_corpus_so_the_granularity_is_visible() -> None:
    """Which corpus answered is invisible from the request and changes the scale.

    A budget component carries up to 520 h and a historical task tops out at 71.
    The prefix of the cited id is the only way to see, from outside, which of the
    two the model was reasoning over.
    """
    verdict = _source_verdict(["BUD-2024-005", "TASK-2024-0012"], ESTIMATION_CASE, CORPUS)
    assert verdict["budgets"] == 1 and verdict["tasks"] == 1


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def test_summary_counts_each_kind_of_failure_apart() -> None:
    evaluations = [
        {"type": "estimation", "passed": True, "latency_ms": 1000.0, "abs_error_hours": 100,
         "sources": {"cited": 3, "fabricated": []}},
        {"type": "estimation", "passed": False, "latency_ms": 3000.0, "abs_error_hours": 500,
         "sources": {"cited": 2, "fabricated": ["TASK-9999-0001"]}},
        {"type": "abstention", "passed": True, "latency_ms": 2000.0,
         "sources": {"cited": 0, "fabricated": []}},
        {"type": "error", "passed": False, "latency_ms": 50.0, "sources": {}},
    ]
    metrics = summarise(evaluations)
    assert metrics["within_range_rate"] == 0.5
    assert metrics["mean_absolute_error_hours"] == 300
    assert metrics["abstention_correct"] is True
    assert metrics["error_rate"] == 0.25
    assert metrics["hallucinated_sources"] == 1
    assert metrics["hallucination_rate"] == 0.2
    assert metrics["cases_passed"] == 2


def test_p95_survives_a_single_sample() -> None:
    assert _percentile([], 95) is None
    assert _percentile([1200.0], 95) == 1200.0
    assert _percentile([100.0, 200.0, 300.0, 400.0], 95) == 400.0


# --------------------------------------------------------------------------- #
# The shipped golden set
# --------------------------------------------------------------------------- #


def test_the_shipped_golden_set_loads_and_holds_its_shape() -> None:
    doc = load_golden_set()
    assert doc["hours_per_day"] == 8
    cases = doc["cases"]
    assert len(cases) >= 5
    assert sum(1 for c in cases if c.get("expect_abstention")) == 1
    difficulties = {c["difficulty"] for c in cases}
    # The statement asks for easy/frequent, medium-high, an edge case and an
    # abstention; the small one is ours, against a system that answers the
    # sector median to everything.
    assert {"easy", "medium-high", "edge", "abstention", "small"} <= difficulties
    for case in cases:
        if case.get("expect_abstention"):
            assert case["expected_hours"] is None and case["acceptable_range_hours"] is None
            continue
        low, high = case["acceptable_range_hours"]
        assert low < case["expected_hours"] < high, case["id"]
        # Every band has to be justified against real history, which is what
        # keeps the ruler from being straight but wrong.
        assert len(case["notes"]) > 200, case["id"]


@pytest.mark.parametrize(
    "broken, message",
    [
        ({"cases": []}, "cases"),
        ({"hours_per_day": 8, "cases": [{"id": "a", "transcript": "x" * 200,
                                         "acceptable_range_hours": [10, 5]}]}, "acceptable_range"),
        ({"hours_per_day": 8, "cases": [{"id": "a", "transcript": "corto"}]}, "100 characters"),
        ({"cases": [{"id": "a", "transcript": "x" * 200,
                     "acceptable_range_hours": [1, 2]}]}, "hours_per_day"),
    ],
)
def test_a_malformed_golden_set_is_refused_rather_than_half_used(tmp_path, broken, message) -> None:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_golden_set(path)


def test_a_set_without_an_abstention_case_is_refused(tmp_path) -> None:
    """The check that keeps a healthy-looking report from being meaningless.

    Drop the abstention case and every remaining metric still computes: the
    accuracy rate looks the same and the safety signal simply disappears.
    """
    path = tmp_path / "golden.json"
    path.write_text(
        json.dumps({"hours_per_day": 8, "cases": [
            {"id": "a", "transcript": "x" * 200, "acceptable_range_hours": [10, 20]}
        ]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="abstention"):
        load_golden_set(path)
