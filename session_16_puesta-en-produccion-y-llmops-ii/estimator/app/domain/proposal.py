"""The commercial proposal: a finished estimate, written up for the client.

A conductor, like ``estimation_service.py`` — it reads a completed run's state
and composes one LLM call over it. It is deliberately **not** a graph node.

Why not a node. The graph's budget is ``GRAPH_MAX_ROUTING_STEPS``, and the happy
path already spends five of its eight dispatches. A node here would compete for
that budget with the work that produces the estimate, would teach the supervisor
a destination it has no reason to reason about, and would make ``finalize`` stop
being the single terminal. As a separate verb over the finished checkpoint it
costs zero routing steps, touches no topology, and can be retried — or
re-written with a different tone — without re-running the estimation.

The reference implementation reached the same conclusion from the other side:
its own proposal endpoint drafts "from the validated estimate, without
re-running the graph".
"""

from __future__ import annotations

import logfire
import structlog

from app.domain.graph.band import historical_band
from app.domain.graph.llm import stamp_llm, structured_call
from app.domain.schemas.graph_estimation import CommercialProposal
from app.foundation.prompts.loader import render_proposal_prompt

log = structlog.get_logger()

HOURS_PER_DAY = 8.0


class ProposalNotReady(Exception):
    """There is no estimate to write a proposal about."""


def _engineer_days(total_hours: float) -> float:
    return round(total_hours / HOURS_PER_DAY, 1)


async def write_proposal(
    llm,
    *,
    model: str,
    state: dict,
    estimation_id: str,
) -> CommercialProposal:
    """Draft the proposal for a finished run. Raises ``ProposalNotReady`` if it is not."""
    estimate = state.get("estimate") or {}
    components = list(estimate.get("components") or [])
    if not components:
        raise ProposalNotReady("The run has no estimate to write a proposal about.")

    validation = state.get("validation") or {}
    # The band is recomputed rather than read: it lives in the interrupt payload,
    # and a run that never paused has no payload to read it from.
    band = historical_band(state.get("components") or [], state.get("budget_matches") or [])
    total_hours = float(estimate.get("total_hours") or 0.0)

    system_prompt, user_message = render_proposal_prompt(
        project=estimate.get("project") or "Proyecto sin nombre",
        components=components,
        total_hours=total_hours,
        engineer_days=_engineer_days(total_hours),
        notes=estimate.get("notes") or "",
        confidence=state.get("confidence"),
        concerns=list(validation.get("concerns") or []),
        band=dict(band) if band else None,
        # Present only when a reviewer overrode the total, which is a fact the
        # client's document should not silently absorb.
        original_total_hours=estimate.get("original_total_hours"),
    )

    with logfire.span("proposal.write", estimation_id=estimation_id) as span:
        proposal, meta = await structured_call(
            llm,
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            response_model=CommercialProposal,
        )
        stamp_llm(span, meta)

    log.info(
        "proposal_written",
        estimation_id=estimation_id,
        model=model,
        scope_lines=len(proposal.scope),
        assumptions=len(proposal.assumptions),
    )
    return proposal
