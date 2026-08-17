"""Reciprocal Rank Fusion — combine independent rankings into a single one.

The problem RRF solves: the two branches of hybrid search produce scores that are
not comparable. Cosine distance lives in a bounded range where LOWER is better;
``ts_rank`` lives on an open-ended scale where HIGHER is better. Adding them is
adding metres to kilograms.

Normalising both onto a shared scale and combining with weights is the tempting
fix, and it works in a demo and breaks in production: the distributions move with
every query (a query full of rare terms produces huge lexical scores; a purely
conceptual one produces tiny ones), so yesterday's calibration is wrong today.

RRF sidesteps the whole problem by discarding the scores and using only the
POSITIONS::

    rrf_score(d) = sum over branches of  1 / (k + position_i(d))

Note ``position`` is 0-BASED here, unlike the 1-based ranks of the original paper.
The choice is arbitrary (it shifts every score by the same direction and changes no
ordering) but it has to be stated, because the arithmetic below only matches the
implementation under one of the two conventions.

The formula makes RRF **a machine for rewarding consensus**: ranking reasonably
well in several branches beats dominating exactly one. A budget that is 2nd
semantically and 5th lexically scores ``1/61 + 1/64 ≈ 0.0320`` and outranks one
that is 1st semantically and absent lexically, ``1/60 ≈ 0.0167`` — nearly double,
and the exact rescue the literal-match case needs.

On ``k``: small values let the top positions dominate, large values flatten the
differences. 60 comes from the original Cormack et al. (2009) paper and has held
up across very different domains; tuning it before there is measured evidence is
premature optimisation.

Pure and synchronous on purpose — no I/O, no ORM, no settings. It fuses a LIST of
rankings, not exactly two: RRF neither knows nor cares how many branches feed it,
and that generality is what makes it reusable for the query-expansion and
multi-index fan-outs later in the programme.
"""

from __future__ import annotations

DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    rankings: list[list[int]],
    *,
    k: int = DEFAULT_RRF_K,
) -> list[tuple[int, float]]:
    """Fuse several id rankings into one, best first.

    Parameters
    ----------
    rankings:
        One list of chunk ids per branch, each already ordered best→worst. A
        branch that found nothing contributes an empty list, which simply adds no
        score — so a dead branch degrades the result gracefully instead of
        emptying it. Repeated ids within a single ranking count only at their
        first (best) position.
    k:
        Smoothing constant. Must be positive: ``k = 0`` would make a rank-0
        document score ``1/0``.

    Returns
    -------
    list[tuple[int, float]]
        ``(chunk_id, fused_score)`` sorted by descending score. Ties break by
        ascending id, so the output is deterministic — which matters because this
        ordering is what the measurement harness scores.

    Raises
    ------
    ValueError
        If ``k`` is not positive.
    """
    if k <= 0:
        raise ValueError(f"RRF smoothing constant k must be positive, got {k}")

    scores: dict[int, float] = {}
    for ranking in rankings:
        seen: set[int] = set()
        for position, chunk_id in enumerate(ranking):
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
