"""The shared blackboard every agent reads and writes.

Three design rules, all of which the system's behaviour depends on.

**Light state.** Only identifiers and distilled data ever go in here — never a
raw model response. The checkpointer serialises this dict after EVERY node, so a
fat state turns the checkpoint write into the bottleneck of the whole run.

**Accumulators where several writers land.** ``budget_matches``, ``errors``,
``proposals`` and ``routing_trail`` are ``Annotated[..., operator.add]``: a node
returns only what it produced and the reducer appends it to what is already
there. The other fields are last-write-wins, which is right for anything one
agent produces once (``estimate``, ``validation``, ``confidence``) and wrong for
anything several can contribute to — a field that is overwritten under a fan-out
silently keeps one branch's result and drops the rest, with no error anywhere.

**Read it with ``.get()``, not ``[...]``.** Only the ``operator.add`` channels
are pre-seeded (to ``[]``); a plain channel simply does not exist in the state
dict until some node writes it. ``state["routing_steps"]`` therefore raises
``KeyError`` on the very first superstep, which is exactly when the supervisor
needs to read it. Every consumer here uses ``.get(key, default)``.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict


class Component(TypedDict):
    """One piece of the project, as the extractor grouped it.

    ``id`` is assigned by the extractor node, never by the model, and it is what
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

    ``component_id`` is what every join uses and ``component`` is what the
    reviewer reads — the same split as ``Component``, and for the same reason.
    Grouping references by NAME pools the evidence of two components the
    classifier happened to name alike ("Integraciones" for an ERP and a CRM),
    prices both at the median of the merged set, and reports a breakdown that
    is wrong on both lines with a total that still adds up.

    ``reference_budget_id`` is the traceable id of the analogue (in this corpus,
    ``<project>/<module>``) and ``amount`` its recorded engineer-hours, so every
    number in the final estimate can be walked back to the row it came from.

    ``distance`` is the retrieval distance of the match, kept because the
    coherence validator scores confidence partly on how close the evidence
    actually is. The backend has always returned it; Session 13 dropped it on
    the floor.
    """

    component_id: str
    component: str
    reference_budget_id: str
    amount: float
    distance: float


class EstimationState(TypedDict, total=False):
    """What every agent reads and what each of them may update.

    ``total=False`` states the truth the checkpointer already enforces: outside
    the accumulators, a key exists only once somebody has written it.
    """

    # --- Input -------------------------------------------------------------
    transcript: str
    # The business id of this estimation, and the graph's thread_id. It lives in
    # the state (not only in the router) because the human-review payload has to
    # echo it: the reviewer needs to know which estimation they are approving.
    estimation_id: str

    # --- Agent contributions ------------------------------------------------
    requirements: list[str]
    components: list[Component]
    # Accumulator: grows as each component is searched.
    budget_matches: Annotated[list[BudgetMatch], operator.add]
    # Accumulator: the competition pattern of the live session fans several
    # estimators in here. Declared now so that change is a wiring change and not
    # a state rewrite.
    proposals: Annotated[list[dict], operator.add]
    # Accumulator: a node that degrades writes here instead of raising, so one
    # failed step costs its own contribution and not the whole run.
    errors: Annotated[list[str], operator.add]

    # --- Outcome (overwrite semantics: last write wins) ---------------------
    estimate: Optional[dict]
    validation: Optional[dict]
    confidence: Optional[float]

    # --- Human-in-the-loop --------------------------------------------------
    human_decision: Optional[dict]

    # --- Routing bookkeeping ------------------------------------------------
    # The real ceiling on a run. LangGraph's recursion_limit cannot do this job:
    # it is counted per invoke, so a run that pauses for a human and resumes gets
    # a fresh budget every time. This counter is persisted in the checkpoint.
    routing_steps: int
    # Accumulator: one entry per supervisor decision. This is the routing record
    # the tests assert invariants against — the path is non-deterministic, so
    # what gets pinned is "no agent acted before its precondition", not an order.
    routing_trail: Annotated[list[dict], operator.add]

    # "validated" | "needs_review" | "awaiting_human_review"
    # | "routing_budget_exhausted"
    status: Optional[str]
