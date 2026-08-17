"""Unit tests for Reciprocal Rank Fusion.

Pure function, no I/O — so these pin the arithmetic and the properties the rest
of the pipeline relies on: consensus beats a single #1, order is deterministic,
and an empty branch degrades gracefully instead of emptying the result.
"""

from __future__ import annotations

import pytest

from app.generation.rag.retrieval.fusion import DEFAULT_RRF_K, reciprocal_rank_fusion


def test_score_matches_the_formula():
    # Single ranking, k=60: id 7 is at position 0 -> 1/60, id 9 at position 1 -> 1/61.
    fused = reciprocal_rank_fusion([[7, 9]], k=60)
    assert fused == [(7, 1 / 60), (9, 1 / 61)]


def test_consensus_beats_a_single_first_place():
    """The property the whole technique exists for.

    Budget 2 is 2nd semantically and 5th lexically; budget 1 is 1st semantically
    and absent lexically. Appearing reasonably high in BOTH must win — this is
    the "Stripe budget buried at position 14" rescue.
    """
    semantic = [1, 2, 3]
    lexical = [90, 91, 92, 93, 2]

    fused = dict(reciprocal_rank_fusion([semantic, lexical], k=DEFAULT_RRF_K))

    assert fused[2] == pytest.approx(1 / 61 + 1 / 64)
    assert fused[1] == pytest.approx(1 / 60)
    # 0.0320 > 0.0167
    assert fused[2] > fused[1]
    assert next(chunk_id for chunk_id, _ in reciprocal_rank_fusion([semantic, lexical])) == 2


def test_an_empty_branch_degrades_gracefully():
    """A dead branch must add nothing, not erase the surviving ranking."""
    only_semantic = reciprocal_rank_fusion([[4, 5, 6], []])
    assert [chunk_id for chunk_id, _ in only_semantic] == [4, 5, 6]


def test_both_branches_empty_yields_empty():
    assert reciprocal_rank_fusion([[], []]) == []
    assert reciprocal_rank_fusion([]) == []


def test_ties_break_by_ascending_id_for_determinism():
    """Two ids at the same position in different branches score identically.

    The measurement harness scores this exact ordering, so ties must not depend on
    dict iteration order.
    """
    fused = reciprocal_rank_fusion([[30], [10], [20]])
    assert [chunk_id for chunk_id, _ in fused] == [10, 20, 30]


def test_duplicate_id_within_one_ranking_counts_once_at_its_best_position():
    fused = dict(reciprocal_rank_fusion([[5, 5, 5]], k=60))
    assert fused[5] == pytest.approx(1 / 60)


def test_fuses_more_than_two_rankings():
    """RRF is branch-agnostic — query expansion and routing will reuse it."""
    fused = dict(reciprocal_rank_fusion([[1], [1], [1]], k=60))
    assert fused[1] == pytest.approx(3 / 60)


def test_smaller_k_makes_the_top_position_dominate():
    """What the constant actually controls, pinned rather than asserted in prose.

    With a small k the #1-in-one-branch wins; with a large k the flatter curve
    lets the consensus document overtake it.
    """
    semantic, lexical = [1, 2], [90, 91, 92, 2]

    aggressive = dict(reciprocal_rank_fusion([semantic, lexical], k=1))
    flat = dict(reciprocal_rank_fusion([semantic, lexical], k=60))

    assert aggressive[1] > aggressive[2]
    assert flat[2] > flat[1]


@pytest.mark.parametrize("bad_k", [0, -1])
def test_non_positive_k_is_rejected(bad_k):
    with pytest.raises(ValueError, match="must be positive"):
        reciprocal_rank_fusion([[1]], k=bad_k)
