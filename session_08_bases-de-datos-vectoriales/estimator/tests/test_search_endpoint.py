"""HTTP-level tests for ``POST /search``.

The retriever is monkey-patched to a double that returns fixed ``SearchHit``s,
so the test exercises the router's request/response shaping (and the 500 branch)
without embedding a query or touching pgvector. The real cosine ranking is
covered by the end-to-end verification.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_embedder
from app.foundation.persistence.database_async import get_async_session
from app.generation.rag.store.vector_store import SearchHit
from app.main import app


class _FakeEmbedder:
    pass  # non-None sentinel; the faked retriever never calls it


class _FakeRetriever:
    def __init__(self, embedder, store) -> None:
        pass

    async def retrieve(self, query: str, k: int) -> list[SearchHit]:
        hits = [
            SearchHit(
                chunk_id=1,
                document_id=1,
                chunk_type="budget_component",
                content="OAuth 2.0 backend with JWT.",
                distance=0.1234,
                metadata={"client_sector": "finance"},
            ),
            SearchHit(
                chunk_id=2,
                document_id=1,
                chunk_type="budget_component",
                content="REST API for accounts.",
                distance=0.4567,
                metadata={"client_sector": "finance"},
            ),
        ]
        return hits[:k]


async def _fake_async_session():
    yield None


@pytest.fixture
def search_client():
    app.dependency_overrides[get_embedder] = lambda: _FakeEmbedder()
    app.dependency_overrides[get_async_session] = _fake_async_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_search_returns_ranked_results(search_client, monkeypatch):
    monkeypatch.setattr("app.api.search.SemanticRetriever", _FakeRetriever)

    response = search_client.post("/search", json={"query": "fintech auth", "k": 2})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "fintech auth"
    assert body["k"] == 2
    assert isinstance(body["search_time_ms"], int) and body["search_time_ms"] >= 0
    assert len(body["results"]) == 2
    first = body["results"][0]
    assert first == {
        "chunk_id": 1,
        "document_id": 1,
        "chunk_type": "budget_component",
        "content": "OAuth 2.0 backend with JWT.",
        "distance": 0.1234,
        "metadata": {"client_sector": "finance"},
    }
    # Results are returned in ascending distance order (closest first).
    assert body["results"][0]["distance"] < body["results"][1]["distance"]


def test_search_respects_k(search_client, monkeypatch):
    monkeypatch.setattr("app.api.search.SemanticRetriever", _FakeRetriever)

    response = search_client.post("/search", json={"query": "anything", "k": 1})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 1


def test_search_without_embedder_returns_500(search_client):
    app.dependency_overrides[get_embedder] = lambda: None

    response = search_client.post("/search", json={"query": "anything", "k": 5})

    assert response.status_code == 500


def test_search_rejects_invalid_k(search_client):
    # k must be >= 1 (schema validation).
    response = search_client.post("/search", json={"query": "x", "k": 0})
    assert response.status_code == 422
