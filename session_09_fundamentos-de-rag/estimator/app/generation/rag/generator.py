"""Generation stage: grounded estimate + post-generation validation.

The prompt asks for citations; this module is what makes them mean something.
A model that cites ``source 412`` when 412 was never retrieved is not making a
formatting mistake — it is fabricating evidence, and it does so in the exact
shape of a real citation. Validating cited ids against the ids actually placed
in the context block is the cheapest lie detector available, and it runs on
every request.

Retry policy, once and only once: re-prompting is a full generation call, and
a model that invents ids twice with the invalid ones spelled out in the prompt
is not going to converge on a third attempt. Past that, the estimate travels
back flagged for manual review rather than being silently dropped — a flagged
estimate is still useful to a human reviewer; a swallowed one is not.
"""

from __future__ import annotations

import structlog

from app.domain.schemas.rag_estimate import Estimate
from app.foundation.llm.responses import ResponsesClient
from app.foundation.prompts.loader import render_rag_estimation_prompt
from app.generation.rag.context_assembler import AssembledContext
from app.generation.rag.schemas import EstimationQuery

log = structlog.get_logger()

# A breakdown that misses the declared total by more than this is flagged, not
# rejected: the reviewer decides whether it is a rounding artefact or nonsense.
TOTAL_MISMATCH_TOLERANCE = 0.10


def validate_citations(estimate: Estimate, valid_ids: set[int]) -> list[int]:
    """Return the cited source ids that were never retrieved, sorted."""
    cited: set[int] = {citation.source_id for citation in estimate.sources}
    for component in estimate.cost_breakdown:
        cited.update(component.sources)
    return sorted(cited - valid_ids)


def check_coherence(estimate: Estimate) -> list[str]:
    """Non-blocking sanity checks on the model's own output.

    These are cheap invariants the schema cannot express: an "insufficient"
    verdict that still reports numbers, or a breakdown that does not add up to
    the total it declares.
    """
    warnings: list[str] = []

    if estimate.confidence == "insufficient":
        if not estimate.insufficient_context_explanation:
            warnings.append("confidence=insufficient without an explanation")
        if estimate.total_engineer_days is not None or estimate.duration_weeks is not None:
            warnings.append("confidence=insufficient but numeric fields are populated")
    elif estimate.total_engineer_days is None:
        warnings.append("no total_engineer_days on a non-insufficient estimate")

    breakdown_total = sum(component.engineer_days for component in estimate.cost_breakdown)
    total = estimate.total_engineer_days
    if total and breakdown_total:
        drift = abs(breakdown_total - total) / total
        if drift > TOTAL_MISMATCH_TOLERANCE:
            warnings.append(
                f"breakdown sums to {breakdown_total} but total is {total} "
                f"({drift:.0%} off)"
            )

    uncited = [c.name for c in estimate.cost_breakdown if not c.sources]
    if uncited:
        warnings.append(f"components with no source: {', '.join(uncited)}")

    return warnings


class GenerationOutcome:
    """The estimate plus everything a reviewer needs to trust it or not."""

    def __init__(
        self,
        *,
        estimate: Estimate,
        invalid_citations: list[int],
        warnings: list[str],
        retried: bool,
    ) -> None:
        self.estimate = estimate
        self.invalid_citations = invalid_citations
        self.warnings = warnings
        self.retried = retried

    @property
    def needs_manual_review(self) -> bool:
        return bool(self.invalid_citations) or bool(self.warnings)

    @property
    def review_reason(self) -> str | None:
        if self.invalid_citations:
            return f"cited source ids that were never retrieved: {self.invalid_citations}"
        if self.warnings:
            return "; ".join(self.warnings)
        return None


class EstimateGenerator:
    """Context block + structured query → validated :class:`Estimate`."""

    def __init__(
        self,
        client: ResponsesClient,
        *,
        model: str,
        reasoning_effort: str,
        prompt_version: str = "v1",
    ) -> None:
        self._client = client
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._prompt_version = prompt_version

    def generate(
        self, *, context: AssembledContext, query: EstimationQuery | None, search_text: str
    ) -> GenerationOutcome:
        # On the fallback path there is no structured query; the model still
        # needs to know what it is estimating, so the search text stands in.
        query_json = (
            query.model_dump_json(indent=2)
            if query is not None
            else f'{{"function": {search_text!r}}}'
        )

        estimate = self._call(context.block, query_json, invalid_ids=None)
        invalid = validate_citations(estimate, context.valid_source_ids)
        retried = False

        if invalid:
            log.warning(
                "estimate_invalid_citations",
                invalid_ids=invalid,
                valid_ids=sorted(context.valid_source_ids),
                attempt=1,
            )
            retried = True
            estimate = self._call(context.block, query_json, invalid_ids=invalid)
            invalid = validate_citations(estimate, context.valid_source_ids)
            if invalid:
                log.error("estimate_invalid_citations_after_retry", invalid_ids=invalid)

        warnings = check_coherence(estimate)
        if warnings:
            log.warning("estimate_coherence_warnings", warnings=warnings)

        log.info(
            "estimate_generated",
            confidence=estimate.confidence,
            total_engineer_days=estimate.total_engineer_days,
            components=len(estimate.cost_breakdown),
            sources_cited=len(estimate.sources),
            assumptions=len(estimate.assumptions),
            retried=retried,
            invalid_citations=invalid,
        )
        return GenerationOutcome(
            estimate=estimate, invalid_citations=invalid, warnings=warnings, retried=retried
        )

    def _call(self, context_block: str, query_json: str, *, invalid_ids: list[int] | None):
        system, user = render_rag_estimation_prompt(
            context_block=context_block,
            structured_query_json=query_json,
            invalid_ids=invalid_ids,
            version=self._prompt_version,
        )
        return self._client.parse(
            model=self._model,
            system_prompt=system,
            user_content=user,
            schema=Estimate,
            reasoning_effort=self._reasoning_effort,
            stage="generation",
        )
