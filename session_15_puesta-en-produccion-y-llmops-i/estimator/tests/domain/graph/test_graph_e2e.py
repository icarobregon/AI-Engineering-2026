"""The multi-agent system, end to end, with a MemorySaver and doubles.

**What is pinned here is the RESULT and the INVARIANTS, never the path.** The
path is chosen at runtime — that is the whole point of a supervisor — so an
assertion on the exact node order would pin the one thing this session set out
to stop fixing in code. ``routing_trail`` gives the invariants instead: that an
estimate came out, that no agent acted before its precondition was satisfied,
that the routing budget held, that the gate fired when it should and that the
resume left the human's decision in the state.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.domain.graph.schemas import ComponentNarrative, EstimateNarrative

from .conftest import build_test_graph, config, start


def _trail(state: dict) -> list[str]:
    return [entry["next_agent"] for entry in state["routing_trail"]]


# --- the run ----------------------------------------------------------------


async def test_the_system_produces_an_estimate_and_validates_it(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("t1"), config("t1"))

    assert state["status"] == "validated"
    assert state["requirements"]
    assert [c["name"] for c in state["components"]] == ["Backend de negocio", "App móvil"]
    assert state["estimate"]["total_hours"] > 0
    assert state["errors"] == []


async def test_no_agent_acts_before_its_precondition_is_satisfied(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("t2"), config("t2"))
    trail = _trail(state)

    # The order is the supervisor's to choose, but these dependencies are not
    # negotiable: you cannot search for budgets you have no components for.
    assert trail.index("requirements_extractor") < trail.index("budget_searcher")
    assert trail.index("budget_searcher") < trail.index("estimate_generator")
    assert trail.index("estimate_generator") < trail.index("coherence_validator")
    assert trail[-1] in ("human_review_gate", "finalize")


async def test_every_routing_decision_carries_its_reason(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("t3"), config("t3"))

    # The trail is the trace's twin: a decision with no reason is a decision you
    # cannot review afterwards.
    assert all(entry["reason"] for entry in state["routing_trail"])
    assert state["routing_steps"] == len(state["routing_trail"])


async def test_the_routing_budget_is_never_exceeded(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend, max_routing_steps=8)

    state = await graph.ainvoke(start("t4"), config("t4"))

    assert state["routing_steps"] <= 8


async def test_a_supervisor_out_of_budget_finalizes_instead_of_looping(fake_llm, fake_backend):
    # One step is enough to dispatch nothing at all: the ceiling is checked
    # before any routing rule, so a confused router cannot spend the API budget.
    graph = build_test_graph(fake_llm, fake_backend, max_routing_steps=1)

    state = await graph.ainvoke(start("t5"), config("t5"))

    assert state["status"] == "routing_budget_exhausted"
    assert state["routing_steps"] <= 2


async def test_budget_matches_accumulate_one_entry_per_reference(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("t6"), config("t6"))

    # Two components, two references each: the reducer appended all four rather
    # than the last write overwriting the previous one.
    assert len(state["budget_matches"]) == 4
    assert {m["component"] for m in state["budget_matches"]} == {"Backend de negocio", "App móvil"}


async def test_search_uses_the_english_query_not_the_display_name(fake_llm, fake_backend):
    # Measured in Session 12: the corpus is English and the same query in Spanish
    # returns nothing. The component keeps its Spanish name for the human.
    graph = build_test_graph(fake_llm, fake_backend)

    await graph.ainvoke(start("t7"), config("t7"))

    assert fake_backend.seen == [
        "logistics order management backend with REST API",
        "courier mobile app with offline sync",
    ]


async def test_the_mechanical_steps_run_on_the_cheap_model_and_the_estimate_on_the_strong_one(
    fake_llm, fake_backend
):
    graph = build_test_graph(fake_llm, fake_backend, fast_model="cheap", estimate_model="strong")

    await graph.ainvoke(start("t8"), config("t8"))

    # Two cheap reads of the meeting, then the strong model for the prose. The
    # supervisor never had to ask: every hop was a precondition.
    assert [call["model"] for call in fake_llm.calls] == ["cheap", "cheap", "strong"]


async def test_the_hours_come_from_the_tool_not_from_the_model(fake_llm, fake_backend):
    """The grant table is only real if the tool decides something.

    ``calculate_estimate`` prices a component as the median of its references
    plus a flat 15% contingency. Both components here see [90, 82], so both are
    priced at 86 × 1.15 = 98.9 — a number the model was never asked for and
    cannot overrule.
    """
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("t9"), config("t9"))

    assert [c["estimated_hours"] for c in state["estimate"]["components"]] == [98.9, 98.9]
    assert state["estimate"]["total_hours"] == 197.8


async def test_a_failing_search_degrades_into_errors_instead_of_killing_the_run(fake_llm):
    async def broken(query, **kwargs):
        raise RuntimeError("pgvector is down")

    graph = build_test_graph(fake_llm, broken)

    state = await graph.ainvoke(start("t10"), config("t10"))

    # Losing one component's references is recoverable; losing the run is not.
    assert len(state["errors"]) >= 1
    assert state["estimate"] is not None


# --- the confidence signal ----------------------------------------------------


async def test_confidence_weighs_grounding_evidence_and_proximity(fake_llm, fake_backend):
    """Every term named, and reproducible without a model.

    Both components fully grounded (0.5) with two references each (0.3), whose
    distances average 0.2 against a 0.6 cutoff (0.2 × 0.667).
    """
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("c1"), config("c1"))

    assert state["confidence"] == 0.933
    assert state["validation"]["is_coherent"]


async def test_a_component_with_no_precedent_is_counted_once_not_twice(fake_llm, partial_backend):
    """The double count this formula had, and a real run paid for.

    The validation tool reports one issue per unbudgeted component — exactly the
    components `grounded_ratio` already measures. Subtracting the whole issue
    list penalised each of them twice: a real 16-component run scored 0.36 where
    its own evidence said 0.66. Only the issues the tool knows and we do not —
    hours out of band, a total that is not the sum of its parts — are a penalty.
    """
    graph = build_test_graph(fake_llm, partial_backend)

    state = await graph.ainvoke(start("c2"), config("c2"))

    # grounded 1/2 (0.25) + density 1/2 (0.15) + proximity 0.667 (0.133), and
    # nothing subtracted: the missing precedent is already in the first term.
    assert state["confidence"] == 0.533
    assert state["validation"]["concerns"] == ["c2: no historical reference (unbudgeted)"]


# --- what the adversarial review found ----------------------------------------


async def test_a_re_search_adds_no_duplicate_evidence(fake_llm, partial_backend):
    """The bug: a second opinion that inflated the confidence it was checking.

    `budget_matches` is an `operator.add` channel, and re-running an identical
    query returns identical rows — so the reducer counted one real analogue
    twice, `evidence_density` read it as full coverage, and a run whose
    confidence was below the threshold cleared the gate on evidence it already
    had. The searcher now skips components that are already covered and drops
    rows it has seen.
    """
    fake_llm.route_to = "budget_searcher"
    graph = build_test_graph(fake_llm, partial_backend)

    state = await graph.ainvoke(start("d1"), config("d1"))
    trail = _trail(state)

    assert trail.count("budget_searcher") == 2, trail
    # Two references, from the first pass only: the retry found nothing new.
    assert len(state["budget_matches"]) == 2
    assert (
        len({(m["component_id"], m["reference_budget_id"]) for m in state["budget_matches"]}) == 2
    )


async def test_a_re_search_asks_the_question_differently(fake_llm, partial_backend):
    """Repeating the identical query is not a second opinion.

    The retry describes the component another way — its display name and the
    kind of work — and only for what the first pass came back empty on.
    """
    fake_llm.route_to = "budget_searcher"
    graph = build_test_graph(fake_llm, partial_backend)

    await graph.ainvoke(start("d2"), config("d2"))

    # Pass 1: both components, by their English search query. Pass 2: only the
    # one still uncovered, described differently.
    assert partial_backend.seen == [
        "logistics order management backend with REST API",
        "courier mobile app with offline sync",
        "App móvil — mobile",
    ]


async def test_a_run_that_used_its_whole_budget_is_not_reported_as_exhausted(
    fake_llm, partial_backend
):
    """The off-by-one that reported an approved estimate as a failed run.

    The supervisor checks its ceiling BEFORE incrementing, so a run it gave up
    on arrives at finalize with max+1 steps, while a run that spent its last
    legal dispatch reaching the gate arrives with exactly max. Reading the
    counter in two places made both look exhausted, and because that branch is
    checked first, the reviewer's decision was dropped from `status` — the one
    field the business backend routes on.
    """
    fake_llm.route_to = "budget_searcher"
    graph = build_test_graph(fake_llm, partial_backend, max_routing_steps=8)

    result = await graph.ainvoke(start("d3"), config("d3"))
    assert "__interrupt__" in result

    state = await graph.ainvoke(Command(resume={"action": "approve"}), config("d3"))

    assert state["routing_steps"] == 8
    assert state["status"] == "validated"


async def test_a_denied_calculation_reaches_the_human_instead_of_killing_the_run(fake_llm):
    """A refused tool call must degrade, like every other refusal here.

    A transcript with nothing concrete in it makes the classifier return no
    components, and the guard rightly refuses an empty calculation. Letting that
    exception escape aborted the superstep, wrote no status, and parked the
    thread on the node forever — every retry of that estimation_id failed the
    same way and the human gate, which exists for exactly this case, was never
    reached.
    """
    fake_llm._components = []

    async def backend(query, **kwargs):  # pragma: no cover - never called
        return []

    graph = build_test_graph(fake_llm, backend)

    result = await graph.ainvoke(start("d4"), config("d4"))

    assert "__interrupt__" in result
    assert any("denied" in e for e in result["errors"])


async def test_two_components_named_alike_do_not_pool_their_references(fake_llm):
    """The join went by name one level deeper than anyone looked.

    A classifier that names two units of work "Integraciones" made both receive
    the union of both sets of references and be priced at the median of the
    merged set: two wrong lines, and a total that still adds up.
    """
    from app.domain.graph.schemas import ClassifiedComponent

    fake_llm._components = [
        ClassifiedComponent(name="Integraciones", category="integration", search_query="erp"),
        ClassifiedComponent(name="Integraciones", category="integration", search_query="crm"),
    ]
    hours = iter([100.0, 500.0])

    async def backend(query, **kwargs):
        return [{"budget_id": f"B/{query}", "estimated_hours": next(hours), "distance": 0.2}]

    graph = build_test_graph(fake_llm, backend)

    state = await graph.ainvoke(start("d5"), config("d5"))

    # 100 × 1.15 and 500 × 1.15 — not 300 × 1.15 twice.
    assert [c["estimated_hours"] for c in state["estimate"]["components"]] == [115.0, 575.0]


# --- the human gate ----------------------------------------------------------


async def test_a_run_with_no_precedent_pauses_for_a_human(fake_llm, empty_backend):
    graph = build_test_graph(fake_llm, empty_backend)

    result = await graph.ainvoke(start("h1"), config("h1"))

    assert "__interrupt__" in result
    payload = list(result["__interrupt__"])[0].value
    assert payload["estimation_id"] == "h1"
    assert any("no comparable budget" in trigger for trigger in payload["triggers"])
    # The payload is the reviewer's interface: the numbers and the reason to
    # doubt them, not a log line.
    assert payload["estimate"] is not None
    assert payload["confidence"] == 0.0


async def test_the_pause_is_persisted_in_the_checkpoint_and_the_run_is_not_finished(
    fake_llm, empty_backend
):
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, empty_backend, checkpointer)

    await graph.ainvoke(start("h2"), config("h2"))
    snapshot = await graph.aget_state(config("h2"))

    # The pause IS persistence: the process could die here and a different one
    # would pick the run up from this checkpoint.
    assert snapshot.next == ("human_review_gate",)
    assert snapshot.values["estimate"] is not None
    assert snapshot.values.get("status") is None


async def test_resuming_with_an_approval_finishes_the_run(fake_llm, empty_backend):
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, empty_backend, checkpointer)
    await graph.ainvoke(start("h3"), config("h3"))

    decision = {"action": "approve", "reviewer_id": "u-42"}
    state = await graph.ainvoke(Command(resume=decision), config("h3"))

    assert state["status"] == "validated"
    assert state["human_decision"] == decision


async def test_resuming_with_an_adjustment_replaces_the_total_and_keeps_the_original(
    fake_llm, empty_backend
):
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, empty_backend, checkpointer)
    await graph.ainvoke(start("h4"), config("h4"))

    state = await graph.ainvoke(
        Command(resume={"action": "adjust", "adjusted_hours": 180.0}), config("h4")
    )

    assert state["estimate"]["total_hours"] == 180.0
    # What the system produced and what the human decided are both evidence: the
    # gap between them is how the confidence threshold gets calibrated.
    assert state["estimate"]["original_total_hours"] == 0.0
    assert state["status"] == "validated"


async def test_a_rejection_does_not_ship_as_validated(fake_llm, empty_backend):
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, empty_backend, checkpointer)
    await graph.ainvoke(start("h5"), config("h5"))

    state = await graph.ainvoke(
        Command(resume={"action": "reject", "comment": "sin precedente real"}), config("h5")
    )

    assert state["status"] == "needs_review"
    assert state["human_decision"]["comment"] == "sin precedente real"


async def test_resuming_does_not_duplicate_the_accumulators(fake_llm, fake_backend):
    """The reducer concatenates, so a resume that re-sent its inputs would double them."""
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, fake_backend, checkpointer, confidence_threshold=0.99)
    await graph.ainvoke(start("h6"), config("h6"))
    paused = await graph.aget_state(config("h6"))
    matches_before = len(paused.values["budget_matches"])

    state = await graph.ainvoke(Command(resume={"action": "approve"}), config("h6"))

    assert len(state["budget_matches"]) == matches_before


async def test_the_gate_spends_nothing_on_the_pause(fake_llm, empty_backend):
    """On resume LangGraph re-runs the whole node body from its first line.

    That is why the gate does nothing but read the state and interrupt: anything
    it computed above the interrupt would be paid for twice, and anything it
    wrote there would be discarded.
    """
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, empty_backend, checkpointer)
    await graph.ainvoke(start("h7"), config("h7"))
    calls_at_pause = len(fake_llm.calls)

    await graph.ainvoke(Command(resume={"action": "approve"}), config("h7"))

    assert len(fake_llm.calls) == calls_at_pause


async def test_a_confident_run_never_reaches_the_reviewer(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend, confidence_threshold=0.5)

    result = await graph.ainvoke(start("h8"), config("h8"))

    assert "__interrupt__" not in result
    assert "human_review_gate" in _trail(result)
    assert result["status"] == "validated"


# --- persistence -------------------------------------------------------------


async def test_the_state_is_checkpointed_after_every_step(fake_llm, fake_backend):
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, fake_backend, checkpointer)

    await graph.ainvoke(start("p1"), config("p1"))
    history = [snapshot async for snapshot in graph.aget_state_history(config("p1"))]

    # One checkpoint per step: enough to resume from any of them, which is what
    # makes the human gate possible at all. History comes newest first.
    assert len(history) >= 6
    assert history[0].values["status"] == "validated"
    # The oldest snapshot predates the transcript and holds only the reducers'
    # empty lists — the accumulator channels are the only ones that pre-seed.
    assert set(history[-1].values) == {"budget_matches", "errors", "proposals", "routing_trail"}
    sizes = [len(snapshot.values) for snapshot in reversed(history)]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]


async def test_each_thread_id_is_its_own_run(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    await graph.ainvoke(start("a"), config("a"))
    empty = await graph.aget_state(config("b"))

    # The thread_id is the estimation's identity: two estimations must not see
    # each other's state.
    assert empty.values == {}


# --- the id join -------------------------------------------------------------


async def test_components_carry_the_id_the_extractor_assigned(fake_llm, fake_backend):
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("i1"), config("i1"))

    assert [c["id"] for c in state["components"]] == ["c1", "c2"]
    assert [c["component_id"] for c in state["estimate"]["components"]] == ["c1", "c2"]


async def test_an_id_the_model_wrapped_in_brackets_still_finds_its_component(
    fake_llm, fake_backend
):
    """A real run: the brief showed "[c1]" and the model returned "[c1]".

    The identity is ours and unambiguous; the brackets are punctuation. Rejecting
    the line over them would drop the rationale from a correct estimate — which
    is exactly what the first version did, nine times in one run.
    """
    fake_llm._narrative = EstimateNarrative(
        project="RUTA",
        components=[
            ComponentNarrative(component_id="[c1] ", rationale="1 analogue"),
            ComponentNarrative(component_id="c2", rationale="1 analogue"),
        ],
        notes="",
    )
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("i2"), config("i2"))

    assert state["estimate"]["components"][0]["rationale"] == "1 analogue"


async def test_a_component_the_model_never_mentioned_still_gets_its_hours(fake_llm, fake_backend):
    """The narrative is the model's; the numbers are not.

    A model that forgets a component used to lose it from the estimate. Now the
    breakdown is built from the components WE classified, so the worst a silent
    model can do is leave a rationale blank.
    """
    fake_llm._narrative = EstimateNarrative(
        project="RUTA",
        components=[ComponentNarrative(component_id="c1", rationale="1 analogue")],
        notes="",
    )
    graph = build_test_graph(fake_llm, fake_backend)

    state = await graph.ainvoke(start("i3"), config("i3"))

    assert len(state["estimate"]["components"]) == 2
    assert state["estimate"]["components"][1]["estimated_hours"] == 98.9
    assert state["estimate"]["components"][1]["rationale"] == ""


# --- status ------------------------------------------------------------------


async def test_a_reused_thread_cannot_inherit_the_previous_runs_validated_status(
    fake_llm, fake_backend, empty_backend
):
    """``status`` is last-write-wins and the checkpointer restores it.

    When it was written only on success, a thread that had ended "validated"
    kept that value and a run whose evidence had JUST collapsed was answered as
    validated — the one field that says whether a human must look at the
    estimate, lying. ``finalize`` is the single owner and writes it on every
    branch.
    """
    checkpointer = MemorySaver()
    graph = build_test_graph(fake_llm, fake_backend, checkpointer)
    first = await graph.ainvoke(start("r1"), config("r1"))
    assert first["status"] == "validated"

    # A different thread whose evidence never arrives must not read as validated.
    paused = build_test_graph(fake_llm, empty_backend, checkpointer)
    result = await paused.ainvoke(start("r2"), config("r2"))
    snapshot = await paused.aget_state(config("r2"))

    assert "__interrupt__" in result
    assert snapshot.values.get("status") is None


async def test_an_ungrounded_component_carries_no_hours(fake_llm, empty_backend):
    graph = build_test_graph(fake_llm, empty_backend)

    result = await graph.ainvoke(start("s1"), config("s1"))
    state = await graph.aget_state(config("s1"))

    # Inventing a number for work with no precedent is the one failure mode this
    # whole pipeline exists to avoid, and the tool cannot: no references, no hours.
    assert all(not c["grounded"] for c in state.values["estimate"]["components"])
    assert state.values["estimate"]["total_hours"] == 0.0
    assert "__interrupt__" in result


async def test_a_degraded_run_is_never_stamped_validated(fake_llm):
    async def broken(query, **kwargs):
        raise RuntimeError("pgvector is down")

    graph = build_test_graph(fake_llm, broken)

    result = await graph.ainvoke(start("s2"), config("s2"))

    # Every search failed, so the evidence base is incomplete by construction:
    # whatever came out, a human has to look at it.
    assert "__interrupt__" in result


async def test_the_estimate_call_gets_room_to_reason_and_the_cheap_ones_do_not(
    fake_llm, fake_backend
):
    """A reasoning model's thinking counts against max_tokens, and its wall time
    against the client timeout. The first version forwarded the effort but not
    the budget, and the deliverable run died on `litellm.Timeout` after burning
    4000 tokens on reasoning that never reached the JSON.
    """
    graph = build_test_graph(
        fake_llm, fake_backend, reasoning_effort="medium", estimate_max_tokens=64000
    )

    await graph.ainvoke(start("m1"), config("m1"))

    estimate_call = fake_llm.calls[-1]
    assert estimate_call["max_tokens"] == 64000
    assert estimate_call["reasoning_effort"] == "medium"
    # The mechanical steps stay on the cheap defaults: they have nothing to think
    # about and paying reasoning time for them is pure latency.
    assert fake_llm.calls[0]["max_tokens"] is None


async def test_a_graph_without_a_checkpointer_is_refused(fake_llm, fake_backend):
    """``compile(checkpointer=None)`` does not raise, and that is the danger.

    An interrupt in an unpersisted graph halts silently and the result reads like
    a truncated success; the failure only surfaces much later, on a resume that
    cannot happen.
    """
    from app.domain.graph.build import build_graph

    from .conftest import build_test_agents

    try:
        build_graph(build_test_agents(fake_llm, fake_backend), checkpointer=None)
    except ValueError as exc:
        assert "checkpointer" in str(exc)
    else:  # pragma: no cover - the assertion above is the test
        raise AssertionError("a graph with no checkpointer must not compile")
