"""Integration tests for POST /embeddings/ingest.

The real (offline) chunker runs; the embedder is faked so no network is hit.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_embedder
from app.embedding_pipeline.embedder import COST_PER_MILLION_TOKENS_USD
from app.embedding_pipeline.schemas import EmbeddedChunk
from app.main import app
from tests.test_embedding_schemas import make_budget_dict


class FakeEmbedder:
    def embed_many(self, chunks) -> list[EmbeddedChunk]:
        return [EmbeddedChunk(**c.model_dump(), embedding=[0.1, 0.2, 0.3]) for c in chunks]


class BrokenEmbedder:
    def embed_many(self, chunks):
        raise RuntimeError("boom")


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ingest_success_returns_chunks_and_stats(client: TestClient) -> None:
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    payload = [
        make_budget_dict(n_components=2),
        {**make_budget_dict(n_components=1), "budget_id": "BUD-T-002"},
    ]

    response = client.post("/embeddings/ingest", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()

    assert len(body["chunks"]) == 3
    assert all(c["embedding"] == [0.1, 0.2, 0.3] for c in body["chunks"])

    stats = body["stats"]
    assert stats["total_budgets"] == 2
    assert stats["total_chunks"] == 3
    assert stats["total_tokens"] == sum(c["token_count"] for c in body["chunks"])
    expected_cost = stats["total_tokens"] * COST_PER_MILLION_TOKENS_USD / 1_000_000
    assert stats["estimated_cost_usd"] == pytest.approx(expected_cost)


def test_ingest_returns_503_without_embedder(client: TestClient) -> None:
    app.dependency_overrides[get_embedder] = lambda: None
    response = client.post("/embeddings/ingest", json=[make_budget_dict()])
    assert response.status_code == 503


def test_ingest_returns_422_on_invalid_payload(client: TestClient) -> None:
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    bad = make_budget_dict(sector="banking")  # sector not in the Literal
    response = client.post("/embeddings/ingest", json=[bad])
    assert response.status_code == 422


def test_ingest_returns_500_when_embedding_fails(client: TestClient) -> None:
    app.dependency_overrides[get_embedder] = lambda: BrokenEmbedder()
    response = client.post("/embeddings/ingest", json=[make_budget_dict()])
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to generate embeddings."
