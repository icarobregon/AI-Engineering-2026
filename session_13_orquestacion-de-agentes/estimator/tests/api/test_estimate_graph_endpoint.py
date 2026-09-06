"""POST /v1/estimate/graph — the contract the business backend sees (S13).

The point of these tests is that the graph is invisible from outside. The
request is a transcript, the response is an estimate with a ``status``, and the
orchestration underneath is the AI service's business — the day the graph is
replaced, none of this moves.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import security
from app.main import app

EST_KEY = "estimate-secret"
HEADERS = {"X-API-Key": EST_KEY}
PAYLOAD = {"transcript": "Reunión: backend de pedidos y app de repartidores."}


@pytest.fixture(autouse=True)
def stub_keys(monkeypatch):
    monkeypatch.setattr(
        security,
        "get_settings",
        lambda: type("S", (), {"RETRIEVAL_API_KEY": "r", "ESTIMATE_API_KEY": EST_KEY})(),
    )
    yield


class FakeSnapshot:
    def __init__(self, values: dict, nxt: tuple = ()):
        self.values = values
        self.next = nxt


class FakeGraph:
    """Records the config it was invoked with and returns a canned final state.

    ``persisted`` is what the checkpointer already holds for the thread: empty
    for a first run, populated for a thread that already finished.
    """

    def __init__(self, state: dict, persisted: dict | None = None, nxt: tuple = ()):
        self.state = state
        self.persisted = persisted or {}
        self.nxt = nxt
        self.calls: list[tuple[dict, dict]] = []

    async def aget_state(self, config):
        return FakeSnapshot(self.persisted, self.nxt)

    async def ainvoke(self, inputs, config):
        self.calls.append((inputs, config))
        return self.state


@pytest.fixture
def graph_state():
    return {
        "estimate": {"project": "RUTA", "total_hours": 172.0, "components": []},
        "status": "validated",
        "errors": [],
    }


def _install(graph):
    app.state.graph = graph
    return graph


def test_returns_the_estimate_and_its_status(client: TestClient, graph_state):
    _install(FakeGraph(graph_state))

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "validated"
    assert body["estimate"]["total_hours"] == 172.0
    assert body["errors"] == []
    assert body["estimation_id"]


def test_the_estimation_id_becomes_the_thread_id(client: TestClient, graph_state):
    graph = _install(FakeGraph(graph_state))

    response = client.post(
        "/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-42"}, headers=HEADERS
    )

    assert response.json()["estimation_id"] == "EST-42"
    _inputs, config = graph.calls[0]
    assert config["configurable"]["thread_id"] == "EST-42"


def test_only_new_input_is_sent_never_accumulator_fields(client: TestClient, graph_state):
    # Passing budget_matches or errors on a resume would make their reducers
    # concatenate them with what is already persisted.
    graph = _install(FakeGraph(graph_state))

    client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    inputs, _config = graph.calls[0]
    assert set(inputs) == {"transcript"}


def test_a_flagged_run_still_answers_200_with_its_reasons(client: TestClient):
    _install(
        FakeGraph(
            {
                "estimate": {"project": "RUTA", "total_hours": 0.0, "components": []},
                "status": "needs_review",
                "errors": ["validate: total 9999.0h does not match the sum of its parts (0.0h)"],
            }
        )
    )

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    # needs_review is an outcome of the flow, not a transport failure: the
    # business backend gets the estimate and the reasons, and decides.
    assert response.status_code == 200
    assert response.json()["status"] == "needs_review"
    assert response.json()["errors"]


def test_requires_the_estimate_api_key(client: TestClient, graph_state):
    _install(FakeGraph(graph_state))

    assert client.post("/v1/estimate/graph", json=PAYLOAD).status_code == 401


def test_answers_503_when_the_graph_has_no_checkpointer(client: TestClient):
    # The lifespan leaves app.state.graph as None when Postgres is unreachable.
    # Saying so beats quietly running a graph that persists nothing.
    app.state.graph = None

    response = client.post("/v1/estimate/graph", json=PAYLOAD, headers=HEADERS)

    assert response.status_code == 503


def test_a_graph_failure_becomes_a_502(client: TestClient):
    class Broken(FakeGraph):
        async def ainvoke(self, inputs, config):
            raise RuntimeError("checkpointer connection lost")

    _install(Broken({}))

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


def test_an_unfinished_thread_is_resumed(client: TestClient, graph_state):
    # next non-empty means the run stopped mid-flight; that IS a resume.
    graph = _install(
        FakeGraph(graph_state, persisted={"transcript": "..."}, nxt=("generate_estimate",))
    )

    client.post("/v1/estimate/graph", json={**PAYLOAD, "estimation_id": "EST-7"}, headers=HEADERS)

    assert len(graph.calls) == 1
