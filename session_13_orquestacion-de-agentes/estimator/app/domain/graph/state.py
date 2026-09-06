"""The shared, typed state that travels through the estimation graph.

Two design rules, both of which the graph's behaviour depends on.

**Light state.** Only identifiers and distilled data ever go in here — never a
raw model response. The checkpointer serialises this dict after EVERY node, so a
fat state turns the checkpoint write into the bottleneck of the whole run.

**Accumulators where concurrency will land.** ``budget_matches`` and ``errors``
are ``Annotated[..., operator.add]``: a node returns only what it produced and
the reducer appends it to what is already there. Every other field is
last-write-wins. The pre-work graph is sequential, so plain overwrite would work
today — they are accumulators because the live session fans ``search_budgets``
out per component, and a field that is overwritten under a fan-out silently
keeps one branch's result and drops the rest. Deciding this now is what makes
that change a wiring change instead of a state rewrite.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict


class Component(TypedDict):
    """One piece of the project, as the classifier grouped it.

    ``id`` is assigned by the classifier node, never by the model, and it is what
    every later join uses. Matching components by their NAME looked fine until a
    real run: the estimate came back naming them "Backend de negocio (backend)"
    — the model had echoed the label the prompt showed it — and the grounding
    check then reported all seven components as unbacked. Joining on prose the
    model is free to rewrite is a bug waiting for a run.

    ``search_query`` is the retrieval-facing rendering of the same component, in
    ENGLISH. It is a third field the skeleton does not have, and it is here
    because of a result measured in Session 12: the historical corpus is written
    in English, and the identical query in Spanish returned 0 rows where the
    English one returned 5. ``name`` stays in the language of the meeting because
    it is what the human reads in the estimate; the query is a machine artefact
    and belongs in the corpus's language.
    """

    id: str
    name: str
    category: str
    search_query: str


class BudgetMatch(TypedDict):
    """One historical reference found for one component.

    ``reference_budget_id`` is the traceable id of the analogue (in this corpus,
    ``<project>/<module>``) and ``amount`` its recorded engineer-hours, so every
    number in the final estimate can be walked back to the row it came from.
    """

    component: str
    reference_budget_id: str
    amount: float


class EstimationState(TypedDict):
    """What every node reads and what each of them may update."""

    transcript: str
    requirements: list[str]
    components: list[Component]
    # Accumulator: grows as each component is searched.
    budget_matches: Annotated[list[BudgetMatch], operator.add]
    estimate: Optional[dict]
    # "validated" | "needs_review"
    status: Optional[str]
    # Accumulator: a node that degrades writes here instead of raising, so one
    # failed step costs its own contribution and not the whole run.
    errors: Annotated[list[str], operator.add]
