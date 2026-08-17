"""Unit tests for the measurement harness's metric functions (Session 10).

The harness is a script and deliberately has no infrastructure around it — but a
wrong metric silently produces a wrong deliverable, and the deliverable IS the
exercise. These three functions import nothing from ``app``, so they need no
fixtures, no database and no container.

They also pin the two defects found in review: ``precision_at_k`` used to divide by
what was returned rather than by ``k`` (rewarding a configuration for retrieving
less), and ``recall_at_k`` used to return 0.0 for a query with no relevant documents
(reporting "found nothing" where there was nothing to find, so a deliberate
soft-fail would have read as a retrieval regression).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_retrieval import (  # noqa: E402
    dedupe_preserving_order,
    precision_at_k,
    recall_at_k,
)

RELEVANT = {"BUD-A", "BUD-B"}


# --------------------------------------------------------------------------- #
# precision_at_k
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "retrieved,expected",
    [
        (["BUD-A", "BUD-B", "BUD-A", "BUD-B", "BUD-A"], 1.0),  # all five relevant
        (["BUD-A", "BUD-B", "BUD-A", "BUD-B", "BUD-X"], 0.8),  # four of five
        (["BUD-X", "BUD-Y", "BUD-Z", "BUD-W", "BUD-V"], 0.0),  # none
    ],
)
def test_precision_over_a_full_result_set(retrieved, expected):
    assert precision_at_k(retrieved, RELEVANT, 5) == pytest.approx(expected)


def test_precision_penalises_a_short_result_set():
    """The defect this test exists for: retrieving LESS must not score higher.

    Two relevant chunks out of two returned is 0.40 at k=5, not 1.00 — the consumer
    asked for five references and got two. Dividing by what came back would rank a
    configuration that returns 2/2 above one that returns 4/5.
    """
    short = precision_at_k(["BUD-A", "BUD-B"], RELEVANT, 5)
    full = precision_at_k(["BUD-A", "BUD-B", "BUD-A", "BUD-B", "BUD-X"], RELEVANT, 5)

    assert short == pytest.approx(0.4)
    assert full == pytest.approx(0.8)
    assert full > short


def test_precision_of_an_empty_result_set_is_zero():
    assert precision_at_k([], RELEVANT, 5) == 0.0


def test_precision_ignores_results_beyond_k():
    """Only the top k reach the generator, so only they count."""
    retrieved = ["BUD-X"] * 5 + ["BUD-A"] * 5
    assert precision_at_k(retrieved, RELEVANT, 5) == 0.0


def test_precision_counts_repeated_parent_budgets_each_time():
    """One budget legitimately occupies several slots (one chunk per component),
    and each slot it occupies is a slot of real context."""
    assert precision_at_k(["BUD-A"] * 5, RELEVANT, 5) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# recall_at_k
# --------------------------------------------------------------------------- #


def test_recall_counts_distinct_relevant_budgets_found():
    assert recall_at_k(["BUD-A", "BUD-A", "BUD-A"], RELEVANT, 5) == pytest.approx(0.5)
    assert recall_at_k(["BUD-A", "BUD-B", "BUD-X"], RELEVANT, 5) == pytest.approx(1.0)


def test_recall_of_an_empty_result_set_is_zero():
    assert recall_at_k([], RELEVANT, 5) == 0.0


def test_recall_ignores_relevant_budgets_beyond_k():
    assert recall_at_k(["BUD-X"] * 5 + ["BUD-A"], RELEVANT, 5) == 0.0


def test_recall_refuses_a_query_with_no_ground_truth():
    """Undefined, not zero: an off-corpus negative case has nothing to find, and
    averaging a 0.0 into the table would report a regression that did not happen."""
    with pytest.raises(ValueError, match="undefined"):
        recall_at_k(["BUD-A"], set(), 5)


# --------------------------------------------------------------------------- #
# dedupe_preserving_order
# --------------------------------------------------------------------------- #


def test_dedupe_keeps_the_best_ranked_occurrence():
    assert dedupe_preserving_order(["B", "A", "B", "C", "A"]) == ["B", "A", "C"]


def test_dedupe_of_an_empty_list_is_empty():
    assert dedupe_preserving_order([]) == []
