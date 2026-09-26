"""Unit tests for post-generation validation (Sessions 9 and 11)."""

from __future__ import annotations

from app.generation.rag.schemas import (
    Estimate,
    RetrievedChunk,
    SourceCitation,
    SourceReference,
    TaskItem,
    WorkModule,
)
from app.generation.rag.validation import (
    check_coherence,
    enforce_citation_policy,
    verify_citations,
)


def _chunk(chunk_id: int) -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content="Component: Auth\nEstimated hours: 120",
        sector="finance",
        project_year=2024,
        chunk_type="budget_component",
        distance=0.3,
        budget_id=f"BUD-2024-{chunk_id:03d}",
    )


def _ref(chunk_id: int) -> SourceReference:
    """A per-line citation, as the model emits it (document_id left to the service)."""
    return SourceReference(chunk_id=chunk_id, evidence="Estimated hours: 120")


def _estimate(
    *, source_ids: list[int], component_sources: list[int], confidence="high"
) -> Estimate:
    return Estimate(
        total_engineer_days=20,
        duration_weeks=4,
        modules=[
            WorkModule(
                name="Authentication",
                tasks=[
                    TaskItem(
                        name="Auth",
                        sources=[_ref(cid) for cid in component_sources],
                        grounded=bool(component_sources),
                        engineer_days=20,
                    )
                ],
            )
        ],
        sources=[
            SourceCitation(source_id=sid, relevance="primary", used_for="auth")
            for sid in source_ids
        ],
        assumptions=[],
        confidence=confidence,
        reasoning="Derived from retrieved budgets.",
    )


def test_dangling_source_ids_empty_when_every_citation_resolves():
    chunks = [_chunk(1), _chunk(2)]
    estimate = _estimate(source_ids=[1, 2], component_sources=[1])
    assert verify_citations(estimate, chunks).dangling_source_ids == []


def test_dangling_source_ids_flags_fabricated_ids():
    chunks = [_chunk(1), _chunk(2)]
    # cites 99 (top-level) and 42 (inside a component) — neither retrieved.
    estimate = _estimate(source_ids=[1, 99], component_sources=[42])
    assert verify_citations(estimate, chunks).dangling_source_ids == [42, 99]


def test_dangling_source_ids_empty_when_nothing_is_cited():
    chunks = [_chunk(1)]
    estimate = _estimate(source_ids=[], component_sources=[])
    assert verify_citations(estimate, chunks).dangling_source_ids == []


def test_dangling_source_ids_flags_every_cited_id_when_retrieval_was_empty():
    estimate = _estimate(source_ids=[1], component_sources=[2])
    assert verify_citations(estimate, []).dangling_source_ids == [1, 2]


def test_check_coherence_insufficient_with_nulls_is_coherent():
    estimate = Estimate(
        total_engineer_days=None,
        duration_weeks=None,
        confidence="insufficient",
        reasoning="no sources",
        insufficient_context_explanation="No relevant budgets retrieved.",
    )
    assert check_coherence(estimate) is True


def test_check_coherence_insufficient_with_numbers_is_incoherent():
    estimate = Estimate(
        total_engineer_days=10,
        duration_weeks=2,
        confidence="insufficient",
        reasoning="contradiction",
        insufficient_context_explanation="",
    )
    assert check_coherence(estimate) is False


def test_check_coherence_non_insufficient_always_true():
    estimate = _estimate(source_ids=[1], component_sources=[1], confidence="low")
    assert check_coherence(estimate) is True


# --- Session 11: per-line citation verification and policy -------------------


def _line(name: str, *, cited: list[int], grounded: bool, days: int | None) -> TaskItem:
    return TaskItem(
        name=name,
        sources=[_ref(cid) for cid in cited],
        grounded=grounded,
        engineer_days=days,
    )


def _estimate_of(
    tasks: list[TaskItem], *, total: int | None, source_ids: list[int] = []
) -> Estimate:
    return Estimate(
        total_engineer_days=total,
        duration_weeks=4,
        modules=[WorkModule(name="Payments", tasks=tasks)],
        sources=[
            SourceCitation(source_id=sid, relevance="primary", used_for="payments")
            for sid in source_ids
        ],
        confidence="high",
        reasoning="Derived from retrieved budgets.",
    )


def test_verify_citations_marks_line_grounded_when_every_cited_chunk_was_retrieved():
    report = verify_citations(
        _estimate_of([_line("Checkout", cited=[1, 2], grounded=True, days=10)], total=10),
        [_chunk(1), _chunk(2)],
    )
    assert (report.grounded, report.dangling, report.insufficient) == (1, 0, 0)
    assert report.lines[0].status == "grounded"
    assert report.lines[0].cited_chunk_ids == [1, 2]
    assert report.dangling_source_ids == []


def test_verify_citations_detects_a_dangling_citation_planted_on_purpose():
    # Criterion: the check must catch a citation whose chunk never reached the LLM.
    report = verify_citations(
        _estimate_of([_line("Checkout", cited=[1, 999], grounded=True, days=10)], total=10),
        [_chunk(1), _chunk(2)],
    )
    assert report.lines[0].status == "dangling"
    assert report.lines[0].dangling_chunk_ids == [999]
    assert report.dangling_source_ids == [999]


def test_verify_citations_marks_dangling_when_a_grounded_line_cites_nothing():
    report = verify_citations(
        _estimate_of([_line("Checkout", cited=[], grounded=True, days=10)], total=10),
        [_chunk(1)],
    )
    assert report.lines[0].status == "dangling"
    # Nothing was cited, so no id can be reported as fabricated.
    assert report.dangling_source_ids == []


def test_verify_citations_marks_an_ungrounded_line_as_insufficient():
    report = verify_citations(
        _estimate_of([_line("Fraud rules", cited=[], grounded=False, days=None)], total=None),
        [_chunk(1)],
    )
    assert report.lines[0].status == "insufficient"
    assert (report.grounded, report.dangling, report.insufficient) == (0, 0, 1)


def test_enforce_citation_policy_resolves_the_parent_document_of_each_citation():
    estimate = _estimate_of([_line("Checkout", cited=[1], grounded=True, days=10)], total=10)
    assert estimate.modules[0].tasks[0].sources[0].document_id == ""

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert served.modules[0].tasks[0].sources[0].document_id == "BUD-2024-001"


def test_enforce_citation_policy_demotes_a_line_whose_only_citation_is_dangling():
    estimate = _estimate_of(
        [
            _line("Checkout", cited=[1], grounded=True, days=10),
            _line("Payouts", cited=[999], grounded=True, days=7),
        ],
        total=17,
    )

    served = enforce_citation_policy(estimate, [_chunk(1)])

    payouts = served.modules[0].tasks[1]
    assert payouts.sources == []
    assert payouts.grounded is False
    assert payouts.engineer_days is None
    # The total is re-derived from what survived, so it still equals its parts.
    assert served.total_engineer_days == 10


def test_enforce_citation_policy_strips_hours_from_an_ungrounded_line():
    # Criterion: a line with no support is never served carrying a number.
    estimate = _estimate_of(
        [
            _line("Checkout", cited=[1], grounded=True, days=10),
            _line("Fraud rules", cited=[], grounded=False, days=40),
        ],
        total=50,
    )

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert served.modules[0].tasks[1].engineer_days is None
    assert served.total_engineer_days == 10


def test_enforce_citation_policy_drops_top_level_citations_that_do_not_resolve():
    estimate = _estimate_of(
        [_line("Checkout", cited=[1], grounded=True, days=10)], total=10, source_ids=[1, 999]
    )

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert [c.source_id for c in served.sources] == [1]


def test_enforce_citation_policy_collapses_to_insufficient_when_no_line_survives():
    estimate = _estimate_of([_line("Checkout", cited=[999], grounded=True, days=10)], total=10)

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert served.confidence == "insufficient"
    assert served.modules == []
    assert served.total_engineer_days is None
    assert served.insufficient_context_explanation
    assert check_coherence(served) is True


def test_enforce_citation_policy_is_a_noop_on_an_already_clean_estimate():
    estimate = _estimate_of([_line("Checkout", cited=[1], grounded=True, days=10)], total=10)

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert served.total_engineer_days == 10
    assert served.modules[0].tasks[0].grounded is True
    assert verify_citations(served, [_chunk(1)]).dangling == 0


def test_enforce_citation_policy_keeps_the_models_own_insufficient_explanation():
    # The model itself declared the context insufficient and said why; the collapse
    # branch also catches that case and must not overwrite its reason with ours.
    estimate = Estimate(
        total_engineer_days=None,
        duration_weeks=None,
        modules=[],
        confidence="insufficient",
        reasoning="r",
        insufficient_context_explanation="The brief never says what to build.",
    )

    served = enforce_citation_policy(estimate, [_chunk(1)])

    assert served.insufficient_context_explanation == "The brief never says what to build."
