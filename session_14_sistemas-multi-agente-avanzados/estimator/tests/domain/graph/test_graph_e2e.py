"""The estimation graph, end to end, with a MemorySaver and doubles.

What these tests pin is what the exercise asks for: the topology, the typed
state with its accumulators, nodes that return partial updates and decide
nothing about who runs next, and a checkpoint after every step.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END

from app.domain.graph.build import build_graph, route_after_validation
from app.domain.graph.nodes import build_nodes
from app.domain.graph.schemas import DraftEstimate, EstimatedComponent

TRANSCRIPT = "Reunión: necesitamos un backend de pedidos y una app para repartidores."


def _graph(fake_llm, fake_backend, checkpointer=None, **overrides):
    nodes = build_nodes(
        llm=fake_llm,
        search_backend=fake_backend,
        fast_model=overrides.get("fast_model", "gpt-5-mini"),
        estimate_model=overrides.get("estimate_model", "gpt-5"),
    )
    return build_graph(nodes, checkpointer=checkpointer or MemorySaver())


async def test_the_graph_runs_the_five_nodes_and_validates(fake_llm, fake_backend):
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t1"}})

    assert state["status"] == "validated"
    assert state["requirements"]
    assert [c["name"] for c in state["components"]] == ["Backend de negocio", "App móvil"]
    assert state["estimate"]["total_hours"] == 172.0
    assert state["errors"] == []


async def test_nodes_run_in_the_wired_order(fake_llm, fake_backend):
    graph = _graph(fake_llm, fake_backend)

    seen = [
        node
        async for chunk in graph.astream(
            {"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t2"}}, stream_mode="updates"
        )
        for node in chunk
    ]

    assert seen == [
        "extract_requirements",
        "classify_components",
        "search_budgets",
        "generate_estimate",
        "validate_and_consolidate",
    ]


async def test_budget_matches_accumulate_one_entry_per_reference(fake_llm, fake_backend):
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t3"}})

    # Two components, two references each: the reducer appended all four rather
    # than the last node's contribution overwriting the previous one.
    assert len(state["budget_matches"]) == 4
    assert {m["component"] for m in state["budget_matches"]} == {"Backend de negocio", "App móvil"}


async def test_search_uses_the_english_query_not_the_display_name(fake_llm, fake_backend):
    # Measured in Session 12: the corpus is English and the same query in Spanish
    # returns nothing. The component keeps its Spanish name for the human.
    graph = _graph(fake_llm, fake_backend)

    await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t4"}})

    assert fake_backend.seen == [
        "logistics order management backend with REST API",
        "courier mobile app with offline sync",
    ]


async def test_mechanical_steps_run_on_the_cheap_model_and_the_estimate_on_the_strong_one(
    fake_llm, fake_backend
):
    graph = _graph(fake_llm, fake_backend, fast_model="cheap", estimate_model="strong")

    await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t5"}})

    assert [call["model"] for call in fake_llm.calls] == ["cheap", "cheap", "strong"]


async def test_a_failing_search_degrades_into_errors_instead_of_killing_the_run(fake_llm):
    async def broken(query, **kwargs):
        raise RuntimeError("pgvector is down")

    graph = _graph(fake_llm, broken)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t6"}})

    # Losing one component's references is recoverable; losing the run is not.
    assert len(state["errors"]) >= 1
    assert all("RuntimeError" in e for e in state["errors"] if e.startswith("search_budgets"))
    assert state["estimate"] is not None


# --- the conditional edge (Level 3) -----------------------------------------


def test_routing_reads_the_status_the_validator_set():
    assert route_after_validation({"status": "validated"}) == END
    assert route_after_validation({"status": None}) == "flag_for_review"
    assert route_after_validation({}) == "flag_for_review"


async def test_a_failed_validation_routes_to_review_instead_of_ending(fake_llm, fake_backend):
    # The model reports a total that is not the sum of its parts: the guardrail
    # catches it, the EDGE decides where that leads, and the run ends flagged
    # rather than shipping a number nobody checked.
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c1",
                name="Backend de negocio",
                estimated_hours=90.0,
                grounded=True,
                rationale="x",
            )
        ],
        total_hours=9999.0,
        notes="",
    )
    graph = _graph(fake_llm, fake_backend)

    seen = []
    async for chunk in graph.astream(
        {"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t7"}}, stream_mode="updates"
    ):
        seen.extend(chunk)
    state = await graph.aget_state({"configurable": {"thread_id": "t7"}})

    assert seen[-1] == "flag_for_review"
    assert state.values["status"] == "needs_review"
    assert any("does not match the sum" in e for e in state.values["errors"])


async def test_an_ungrounded_claim_is_caught_by_the_guardrails(fake_llm, fake_backend):
    async def empty_backend(query, **kwargs):
        return []

    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c1",
                name="Backend de negocio",
                estimated_hours=90.0,
                grounded=True,
                rationale="invented",
            )
        ],
        total_hours=90.0,
        notes="",
    )
    graph = _graph(fake_llm, empty_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t8"}})

    assert state["status"] == "needs_review"
    assert any("claims grounding with no reference" in e for e in state["errors"])


# --- persistence -------------------------------------------------------------


async def test_the_state_is_checkpointed_after_every_node(fake_llm, fake_backend):
    checkpointer = MemorySaver()
    graph = _graph(fake_llm, fake_backend, checkpointer)
    config = {"configurable": {"thread_id": "t9"}}

    await graph.ainvoke({"transcript": TRANSCRIPT}, config)
    history = [snapshot async for snapshot in graph.aget_state_history(config)]

    # One checkpoint per node plus the pre-input snapshot: enough to resume from
    # any step, which is what makes the live session's human gates possible.
    # History comes newest first.
    assert len(history) >= 6
    assert history[0].values["status"] == "validated"
    # The oldest snapshot predates the transcript and holds only the accumulator
    # defaults — the reducers' empty lists, not an empty state.
    assert set(history[-1].values) == {"budget_matches", "errors"}
    assert any(snapshot.values.get("transcript") == TRANSCRIPT for snapshot in history)
    # Each step persisted strictly more than the one before it: that monotonic
    # growth IS the per-node checkpointing, read from the store itself.
    sizes = [len(snapshot.values) for snapshot in reversed(history)]
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]


async def test_each_thread_id_is_its_own_run(fake_llm, fake_backend):
    graph = _graph(fake_llm, fake_backend)

    await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "a"}})
    empty = await graph.aget_state({"configurable": {"thread_id": "b"}})

    # The thread_id is the estimation's identity: two estimations must not see
    # each other's state.
    assert empty.values == {}


async def test_components_are_joined_by_id_not_by_the_name_the_model_wrote(fake_llm, fake_backend):
    """A real gpt-5 run echoed the label the prompt showed it — "Backend de
    negocio (backend)" — and every component was then reported as unbacked. The
    join is on the id we assign, so the model rewriting a name changes nothing.
    """
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c1",
                name="Backend de negocio (backend)",  # the model's own rendering
                estimated_hours=90.0,
                grounded=True,
                rationale="1 analogue",
            )
        ],
        total_hours=90.0,
        notes="",
    )
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t10"}})

    assert state["status"] == "validated"
    assert state["errors"] == []


async def test_an_estimate_for_a_component_that_was_never_classified_is_caught(
    fake_llm, fake_backend
):
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c99",
                name="Something nobody asked for",
                estimated_hours=90.0,
                grounded=True,
                rationale="",
            )
        ],
        total_hours=90.0,
        notes="",
    )
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t11"}})

    assert state["status"] == "needs_review"
    assert any("not one of the components that were classified" in e for e in state["errors"])


async def test_components_carry_the_id_the_classifier_assigned(fake_llm, fake_backend):
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t12"}})

    assert [c["id"] for c in state["components"]] == ["c1", "c2"]


async def test_an_id_the_model_wrapped_in_brackets_is_still_that_component(fake_llm, fake_backend):
    """Another real run: the brief showed "[c1]" and the model returned "[c1]".

    The identity is ours and unambiguous; the brackets are punctuation. Rejecting
    the line over them would flag a correct estimate — which is exactly what the
    first version did, nine times in one run.
    """
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="[c1] ",
                name="Backend de negocio",
                estimated_hours=90.0,
                grounded=True,
                rationale="1 analogue",
            )
        ],
        total_hours=90.0,
        notes="",
    )
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t13"}})

    assert state["status"] == "validated"
    assert state["errors"] == []


async def test_a_reused_thread_cannot_inherit_the_previous_runs_validated_status(
    fake_llm, fake_backend
):
    """The worst failure the review found, reproduced.

    ``status`` is last-write-wins and the checkpointer restores it. When the
    validator wrote it only on success, a thread that had ended "validated" kept
    that value, the edge read it, and a run whose guardrails had JUST failed was
    answered as validated — the one field that says whether a human must look at
    the estimate, lying.
    """
    checkpointer = MemorySaver()
    config = {"configurable": {"thread_id": "reused"}}
    graph = _graph(fake_llm, fake_backend, checkpointer)

    first = await graph.ainvoke({"transcript": TRANSCRIPT}, config)
    assert first["status"] == "validated"

    # Same thread, and this time the estimate does not add up.
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c1", name="Backend", estimated_hours=90.0, grounded=True, rationale=""
            )
        ],
        total_hours=9999.0,
        notes="",
    )
    second = await graph.ainvoke({"transcript": TRANSCRIPT}, config)

    assert second["status"] == "needs_review"
    assert any("does not match the sum" in e for e in second["errors"])


async def test_an_ungrounded_component_may_not_carry_hours(fake_llm, fake_backend):
    # The inverse of the grounding check, and the one that matters more: a line
    # that admits it has no evidence must not contribute to the total.
    fake_llm._estimate = DraftEstimate(
        project="RUTA",
        components=[
            EstimatedComponent(
                component_id="c1",
                name="Backend de negocio",
                estimated_hours=400.0,
                grounded=False,
                rationale="no references found",
            )
        ],
        total_hours=400.0,
        notes="",
    )
    graph = _graph(fake_llm, fake_backend)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t14"}})

    assert state["status"] == "needs_review"
    assert any("not grounded but carries" in e for e in state["errors"])


async def test_a_degraded_run_is_never_stamped_validated(fake_llm):
    async def broken(query, **kwargs):
        raise RuntimeError("pgvector is down")

    graph = _graph(fake_llm, broken)

    state = await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t15"}})

    # Every search failed, so the evidence base is incomplete by construction:
    # whatever the model produced, a human has to look at it.
    assert state["status"] == "needs_review"
    assert any("the run degraded earlier" in e for e in state["errors"])


async def test_the_estimate_call_gets_room_to_reason_and_the_cheap_ones_do_not(
    fake_llm, fake_backend
):
    """A reasoning model's thinking counts against max_tokens, and its wall time
    against the client timeout. The first version forwarded the effort but not
    the budget, and the deliverable run died on `litellm.Timeout` after burning
    4000 tokens on reasoning that never reached the JSON.
    """
    nodes = build_nodes(
        llm=fake_llm,
        search_backend=fake_backend,
        fast_model="cheap",
        estimate_model="strong",
        reasoning_effort="medium",
        estimate_max_tokens=64000,
    )
    graph = build_graph(nodes, checkpointer=MemorySaver())

    await graph.ainvoke({"transcript": TRANSCRIPT}, {"configurable": {"thread_id": "t16"}})

    estimate_call = fake_llm.calls[-1]
    assert estimate_call["max_tokens"] == 64000
    assert estimate_call["reasoning_effort"] == "medium"
    # The mechanical steps stay on the cheap defaults: they have nothing to think
    # about and paying reasoning time for them is pure latency.
    assert fake_llm.calls[0]["max_tokens"] is None
