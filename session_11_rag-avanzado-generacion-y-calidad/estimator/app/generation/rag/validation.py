"""Post-generation checks for grounded estimates (Sessions 9 and 11).

Three guards run after the LLM returns an :class:`Estimate`:

* :func:`verify_citations` (S11) — the per-line verdict. Every line is classified
  as ``grounded`` / ``dangling`` / ``insufficient``, and the ids that were never
  retrieved are collected. This REPORTS; it changes nothing.
* :func:`enforce_citation_policy` (S11) — the policy. Resolves each citation's
  parent document, drops citations that do not resolve, demotes the lines left
  without backing, and re-derives the total so it still matches its parts. This
  is what makes "an estimate never leaves the service carrying a citation that
  does not resolve" a property of the code rather than of the prompt.
* :func:`check_coherence` (S09) — the ``insufficient`` confidence level has a
  strict shape (no numbers, an explanation present); a violation is a malformed
  response, not a valid estimate.

The Session 9 ``validate_citations`` is gone: both of its callers now read
``CitationReport.dangling_source_ids``, which is the same set with the per-line
verdict attached.
"""

from __future__ import annotations

from app.generation.rag.schemas import (
    CitationReport,
    Estimate,
    LineCitationCheck,
    RetrievedChunk,
    SourceReference,
    TaskItem,
    WorkModule,
)


def _all_cited_ids(estimate: Estimate) -> set[int]:
    """Every chunk id the estimate cites, top-level citations and lines alike."""
    cited: set[int] = {citation.source_id for citation in estimate.sources}
    for module in estimate.modules:
        for task in module.tasks:
            cited.update(ref.chunk_id for ref in task.sources)
    return cited


def verify_citations(
    estimate: Estimate,
    retrieved_chunks: list[RetrievedChunk],
) -> CitationReport:
    """Classify every line of ``estimate`` against the context it was given.

    A line is:

    * ``insufficient`` when it declared ``grounded=False`` — the honest outcome
      when no source backs it;
    * ``dangling`` when it claims to be grounded but cites nothing, or cites an
      id that was never retrieved — grounding it cannot back;
    * ``grounded`` when every id it cites was really in the context.

    Parameters
    ----------
    estimate:
        The generated estimate to inspect.
    retrieved_chunks:
        The chunks the estimate was supposed to be grounded in — the ones that
        actually reached the prompt, not everything retrieval returned.

    Returns
    -------
    CitationReport
        Per-line verdicts, the counts per status, and the sorted, de-duplicated
        ids that were cited but never retrieved.
    """
    retrieved_ids = {chunk.id for chunk in retrieved_chunks}

    lines: list[LineCitationCheck] = []
    for module in estimate.modules:
        for task in module.tasks:
            cited = [ref.chunk_id for ref in task.sources]
            dangling = sorted({cid for cid in cited if cid not in retrieved_ids})
            if not task.grounded:
                status = "insufficient"
            elif not cited or dangling:
                status = "dangling"
            else:
                status = "grounded"
            lines.append(
                LineCitationCheck(
                    module=module.name,
                    task=task.name,
                    status=status,
                    cited_chunk_ids=cited,
                    dangling_chunk_ids=dangling,
                )
            )

    return CitationReport(
        lines=lines,
        grounded=sum(1 for line in lines if line.status == "grounded"),
        dangling=sum(1 for line in lines if line.status == "dangling"),
        insufficient=sum(1 for line in lines if line.status == "insufficient"),
        dangling_source_ids=sorted(_all_cited_ids(estimate) - retrieved_ids),
    )


def enforce_citation_policy(
    estimate: Estimate,
    retrieved_chunks: list[RetrievedChunk],
) -> Estimate:
    """Return a copy of ``estimate`` that no longer carries unresolvable claims.

    Applied to the estimate the service is about to serve, after the corrective
    retry has had its chance. Four deterministic passes, no LLM involved:

    1. **Resolve.** Each surviving citation gets its parent ``document_id`` from
       the chunk it points at — derived, never taken from the model.
    2. **Prune.** Citations whose chunk was never retrieved are dropped.
    3. **Demote.** A line left with no citation (or that never claimed one) is
       marked ``grounded=False`` and loses its ``engineer_days``: a line without
       evidence must read as "no sufficient source data", not as a number.
    4. **Re-derive.** ``total_engineer_days`` is recomputed from the lines that
       survived, so the total still equals the sum of its parts.

    If no line survives grounded, the estimate as a whole has nothing verifiable
    left to stand on and collapses to the canonical insufficient-context shape
    (no numbers, no modules), which is what :func:`check_coherence` expects.
    """
    retrieved_ids = {chunk.id for chunk in retrieved_chunks}
    document_by_chunk_id = {
        chunk.id: (chunk.source_id or chunk.budget_id or "") for chunk in retrieved_chunks
    }

    modules: list[WorkModule] = []
    grounded_days: list[int] = []
    for module in estimate.modules:
        tasks: list[TaskItem] = []
        for task in module.tasks:
            kept = [
                SourceReference(
                    chunk_id=ref.chunk_id,
                    document_id=document_by_chunk_id[ref.chunk_id],
                    evidence=ref.evidence,
                )
                for ref in task.sources
                if ref.chunk_id in retrieved_ids
            ]
            grounded = task.grounded and bool(kept)
            engineer_days = task.engineer_days if grounded else None
            if engineer_days is not None:
                grounded_days.append(engineer_days)
            tasks.append(
                task.model_copy(
                    update={
                        "sources": kept,
                        "grounded": grounded,
                        "engineer_days": engineer_days,
                    }
                )
            )
        modules.append(module.model_copy(update={"tasks": tasks}))

    if not any(task.grounded for module in modules for task in module.tasks):
        return estimate.model_copy(
            update={
                "modules": [],
                "sources": [],
                "total_engineer_days": None,
                "duration_weeks": None,
                "confidence": "insufficient",
                # The model's own explanation survives when it had one: this branch
                # also catches the estimate that never had lines (the model itself
                # declared the context insufficient), and overwriting its reason
                # with ours would report a failure that did not happen.
                "insufficient_context_explanation": (
                    estimate.insufficient_context_explanation
                    or "No estimate line could be traced back to a retrieved source."
                ),
            }
        )

    return estimate.model_copy(
        update={
            "modules": modules,
            "sources": [c for c in estimate.sources if c.source_id in retrieved_ids],
            "total_engineer_days": sum(grounded_days) if grounded_days else None,
        }
    )


def check_coherence(estimate: Estimate) -> bool:
    """Return whether the estimate's confidence level matches its content.

    When ``confidence == "insufficient"``: both numeric totals must be ``None``,
    ``modules`` must be empty, and ``insufficient_context_explanation`` must be
    non-empty. Any other confidence level is always considered coherent here
    (the numeric checks belong to the schema/business rules, not to this guard).
    """
    if estimate.confidence != "insufficient":
        return True
    return (
        estimate.total_engineer_days is None
        and estimate.duration_weeks is None
        and not estimate.modules
        and bool(estimate.insufficient_context_explanation)
    )
