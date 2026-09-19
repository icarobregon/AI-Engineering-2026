"""``/v1/estimate/graph`` — the contract the business backend sees (S13-S14).

The point of these tests is that the multi-agent system is invisible from
outside. The request is a transcript, the response is an estimate with a
``status``, and the orchestration underneath is the AI service's business.

Session 14 adds exactly one value to ``status`` and two verbs. The business
backend needs a new branch, not a new integration — so these tests pin both the
new surface and the fact that everything else stayed where it was.
"""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command

from app.api import security
from app.main import app

# A unique key per test isolates the slowapi bucket: the limiter is keyed on
# X-API-Key and the estimate routes allow 10/minute, which a module with more
# than ten requests would otherwise exhaust halfway through.
_KEYS = itertools.count()
HEADERS = {"X-API-Key": "estimate-secret-0"}
PAYLOAD = {"transcript": "Reunión: backend de pedidos y app de repartidores."}
REVIEW = {
    "estimation_id": "EST-9",
    "reason": "No comparable budget was found for any component of this project",
    "triggers": ["no comparable budget was found for any component of this project"],
    "estimate": {"project": "RUTA", "total_hours": 0.0, "components": []},
    "confidence": 0.0,
}


@pytest.fixture(autouse=True)
def stub_keys(monkeypatch):
    key = f"estimate-secret-{next(_KEYS)}"
    HEADERS["X-API-Key"] = key
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: type("S", (), {"RETRIEVAL_API_KEY": "r", "ESTIMATE_API_KEY": key})(),
    )
    yield


@pytest.fixture(autouse=True)
def restore_graph():
    """Nothing tears ``app.state.graph`` down by itself, and it is module-level:
    without this the last test to run leaks its double into the next module."""
    previous = getattr(app.state, "graph", None)
    yield
    app.state.graph = previous


class FakeInterrupt:
    def __init__(self, value: dict):
        self.value = value


class FakeTask:
    def __init__(self, interrupts: tuple):
        self.interrupts = interrupts


class FakeSnapshot:
    def __init__(self, values: dict, nxt: tuple = (), interrupts: tuple = ()):
        self.values = values
        self.next = nxt
        self.interrupts = interrupts
        self.tasks = (FakeTask(interrupts),) if interrupts else ()


class FakeGraph:
    """Records what it was invoked with and returns a canned final state.

    ``persisted`` is what the checkpointer already holds for the thread: empty
    for a first run, populated for one that already finished or is paused.
    """

    def __init__(
        self,
        state: dict,
        persisted: dict | None = None,
        nxt: tuple = (),
        interrupts: tuple = (),
    ):
        self.state = state
        self.persisted = persisted or {}
        self.nxt = nxt
        self.interrupts = interrupts
        self.calls: list[tuple[object, dict]] = []

    async def aget_state(self, config):
        return FakeSnapshot(self.persisted, self.nxt, self.interrupts)

    async def ainvoke(self, inputs, config):
        self.calls.append((inputs, config))
        return self.state


@pytest.fixture
def graph_state():
    return {
        "estimate": {"project": "RUTA", "total_hours": 197.8, "components": []},
        "status": "validated",
        "errors": [],
    }


def _install(graph):
    app.state.graph = graph
    return graph


# --- starting a run -----------------------------------------------------------


def test_returns_the_estimate_and_its_status(client: TestClient, graph_state):
    _install(FakeGraph(graph_state))

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "validated"
    assert body["estimate"]["total_hours"] == 197.8
    assert body["errors"] == []
    assert body["estimation_id"]
    assert body["review_payload"] is None


def test_the_estimation_id_becomes_the_thread_id(client: TestClient, graph_state):
    graph = _install(FakeGraph(graph_state))

    response = client.post(
        "/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-42"}, headers=HEADERS
    )

    assert response.json()["estimation_id"] == "EST-42"
    _inputs, config = graph.calls[0]
    assert config["configurable"]["thread_id"] == "EST-42"


def test_only_new_input_is_sent_never_accumulator_fields(client: TestClient, graph_state):
    # Passing budget_matches, errors or routing_trail would make their reducers
    # concatenate them with what is already persisted.
    graph = _install(FakeGraph(graph_state))

    client.post("/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-1"}, headers=HEADERS)

    inputs, _config = graph.calls[0]
    assert set(inputs) == {"transcript", "estimation_id"}


def test_a_flagged_run_still_answers_200_with_its_reasons(client: TestClient):
    _install(
        FakeGraph(
            {
                "estimate": {"project": "RUTA", "total_hours": 0.0, "components": []},
                "status": "needs_review",
                "errors": ["search_budgets(App móvil): RuntimeError"],
            }
        )
    )

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    # needs_review is an outcome of the flow, not a transport failure: the
    # business backend gets the estimate and the reasons, and decides.
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["errors"]


def test_a_run_that_ran_out_of_routing_budget_says_so(client: TestClient):
    _install(FakeGraph({"estimate": None, "status": "routing_budget_exhausted", "errors": []}))

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    # A run that ran out is not a run that passed, and the contract must not let
    # it read as one.
    assert response.status_code == 200
    assert response.json()["status"] == "routing_budget_exhausted"


# --- the pause ----------------------------------------------------------------


def test_a_run_that_pauses_answers_awaiting_human_review_with_the_payload(client: TestClient):
    _install(FakeGraph({"errors": [], "__interrupt__": [FakeInterrupt(REVIEW)]}))

    response = client.post(
        "/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-9"}, headers=HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    # A new VALUE of a field that already existed — not a new contract.
    assert body["status"] == "awaiting_human_review"
    assert body["estimate"] is None
    assert body["review_payload"]["confidence"] == 0.0
    assert body["review_payload"]["triggers"]


def test_a_paused_thread_is_reported_not_restarted(client: TestClient):
    """The bug this branch exists to prevent.

    An interrupted thread has values AND a non-empty ``next``, so the
    finished-check lets it through — and invoking it again would run the whole
    system from the start, appending to every accumulator, while the reviewer
    still has the first run on their screen.
    """
    graph = _install(
        FakeGraph(
            {"status": "validated"},
            persisted={"transcript": "...", "errors": []},
            nxt=("human_review_gate",),
            interrupts=(FakeInterrupt(REVIEW),),
        )
    )

    response = client.post(
        "/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-9"}, headers=HEADERS
    )

    assert response.json()["status"] == "awaiting_human_review"
    assert response.json()["review_payload"]["reason"]
    assert graph.calls == []


# --- resuming -----------------------------------------------------------------


def test_the_resume_endpoint_sends_the_decision_and_returns_the_final_estimate(
    client: TestClient, graph_state
):
    graph = _install(
        FakeGraph(
            graph_state,
            persisted={"transcript": "..."},
            nxt=("human_review_gate",),
            interrupts=(FakeInterrupt(REVIEW),),
        )
    )

    response = client.post(
        "/v1/estimate/graph/EST-9/resume",
        json={"action": "adjust", "adjusted_hours": 180, "reviewer_id": "u-42"},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "validated"
    resumed, config = graph.calls[0]
    assert isinstance(resumed, Command)
    assert resumed.resume["action"] == "adjust"
    assert resumed.resume["adjusted_hours"] == 180
    assert config["configurable"]["thread_id"] == "EST-9"


def test_a_second_reviewer_deciding_the_same_case_does_not_start_a_second_run(
    client: TestClient, graph_state
):
    """Idempotency in the endpoint rather than a lock: the record of who decided
    first is in ``human_decision``, and arbitrating between reviewers is the
    business backend's job, not this service's."""
    graph = _install(FakeGraph({"status": "needs_review"}, persisted=graph_state))

    response = client.post(
        "/v1/estimate/graph/EST-9/resume", json={"action": "approve"}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["status"] == "validated"  # the decided result, not a new run
    assert graph.calls == []


def test_resuming_an_unknown_estimation_is_a_404(client: TestClient):
    _install(FakeGraph({}, persisted={}))

    response = client.post(
        "/v1/estimate/graph/nope/resume", json={"action": "approve"}, headers=HEADERS
    )

    assert response.status_code == 404


def test_a_decision_outside_the_three_actions_is_rejected(client: TestClient, graph_state):
    _install(FakeGraph(graph_state, persisted={"transcript": "..."}))

    response = client.post(
        "/v1/estimate/graph/EST-9/resume", json={"action": "maybe"}, headers=HEADERS
    )

    assert response.status_code == 422


# --- reading the state --------------------------------------------------------


def test_the_state_endpoint_reports_where_a_run_stands(client: TestClient, graph_state):
    _install(
        FakeGraph(
            {},
            persisted=graph_state,
            nxt=("human_review_gate",),
            interrupts=(FakeInterrupt(REVIEW),),
        )
    )

    response = client.get("/v1/estimate/graph/EST-9/state", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["next"] == ["human_review_gate"]
    assert body["review_payload"]["confidence"] == 0.0
    assert body["values"]["status"] == "validated"


def test_the_state_of_an_unknown_estimation_is_a_404(client: TestClient):
    _install(FakeGraph({}, persisted={}))

    assert client.get("/v1/estimate/graph/nope/state", headers=HEADERS).status_code == 404


# --- transport ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/estimate/graph", PAYLOAD),
        ("post", "/v1/estimate/graph/EST-9/resume", {"action": "approve"}),
        ("get", "/v1/estimate/graph/EST-9/state", None),
    ],
)
def test_every_verb_requires_the_estimate_api_key(
    client: TestClient, graph_state, method, path, body
):
    _install(FakeGraph(graph_state, persisted=graph_state))

    response = getattr(client, method)(path, **({"json": body} if body else {}))

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/v1/estimate/graph", PAYLOAD),
        ("post", "/v1/estimate/graph/EST-9/resume", {"action": "approve"}),
        ("get", "/v1/estimate/graph/EST-9/state", None),
    ],
)
def test_every_verb_answers_503_when_the_graph_has_no_checkpointer(
    client: TestClient, method, path, body
):
    # The lifespan leaves app.state.graph as None when Postgres is unreachable.
    # With a human gate in the flow, unpersisted means a pause that can never
    # resume — so saying so matters more than it did in Session 13.
    app.state.graph = None

    response = getattr(client, method)(path, headers=HEADERS, **({"json": body} if body else {}))

    assert response.status_code == 503


def test_a_graph_failure_becomes_a_502(client: TestClient):
    class Broken(FakeGraph):
        async def ainvoke(self, inputs, config):
            raise RuntimeError("checkpointer connection lost")

    _install(Broken({}))

    assert client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS).status_code == 502


def test_a_runaway_routing_loop_becomes_a_502_and_is_logged_as_itself(client: TestClient):
    from langgraph.errors import GraphRecursionError

    class Looping(FakeGraph):
        async def ainvoke(self, inputs, config):
            raise GraphRecursionError("recursion limit reached")

    _install(Looping({}))

    # Same status to the client — it can do nothing differently — but a distinct
    # log event, because this one is diagnosed by reading the routing budget and
    # not by checking whether a provider was down.
    assert client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS).status_code == 502


def test_a_finished_estimation_is_answered_not_estimated_again(client: TestClient, graph_state):
    """Re-invoking a finished thread appends to the accumulator channels: the
    evidence doubles, and a retry whose retrieval failed would still find the
    previous run's matches and certify components as grounded on references it
    never retrieved. A retry with the same business id has to be safe.
    """
    graph = _install(FakeGraph({"status": "needs_review"}, persisted=graph_state))

    response = client.post(
        "/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-42"}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["status"] == "validated"  # the persisted result, not a new run
    assert graph.calls == []


def test_a_thread_that_died_mid_flight_is_re_run(client: TestClient, graph_state):
    """``next`` is non-empty for a paused run AND for one that crashed. Only the
    pending interrupt tells them apart — and without one, restarting is right."""
    graph = _install(
        FakeGraph(graph_state, persisted={"transcript": "..."}, nxt=("estimate_generator",))
    )

    client.post("/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-7"}, headers=HEADERS)

    assert len(graph.calls) == 1
