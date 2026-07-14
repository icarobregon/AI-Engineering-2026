"""HTTP-level tests for the refactored ``POST /embeddings/ingest``.

We bypass Postgres entirely: ``get_async_session`` yields ``None`` and the
``VectorStore`` used inside the router is monkey-patched to an in-memory double.
This exercises the router wiring (chunker → embedder → store, plus the 409 and
500 branches) without any database. The real cosine query over pgvector is
covered by the end-to-end verification, not here.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_embedder
from app.foundation.persistence.database_async import get_async_session
from app.generation.rag.schemas import Chunk, EmbeddedChunk
from app.generation.rag.store.vector_store import DocumentAlreadyExists
from app.main import app


def _budget_payload() -> dict:
    """A minimal but schema-valid ingest request (one budget, two components)."""
    return {
        "source_path": "data/budgets_sample.json#BUD-TEST-001",
        "document_type": "historical_budget",
        "content": {
            "budget_id": "BUD-TEST-001",
            "client_metadata": {"name": "FintechCorp", "sector": "finance", "country": "ES"},
            "project_summary": "Mobile banking API with OAuth 2.0",
            "main_technology": "ruby_on_rails",
            "year": 2024,
            "total_estimated_hours": 200,
            "components": [
                {
                    "component_id": "AUTH-001",
                    "name": "OAuth 2.0 backend",
                    "description": "JWT-based auth with rate limiting.",
                    "tech_stack": ["ruby_on_rails", "postgresql"],
                    "estimated_hours": 120,
                    "complexity": "high",
                    "dependencies": [],
                },
                {
                    "component_id": "API-002",
                    "name": "REST API",
                    "description": "Public REST endpoints for accounts.",
                    "tech_stack": ["ruby_on_rails"],
                    "estimated_hours": 80,
                    "complexity": "medium",
                    "dependencies": ["AUTH-001"],
                },
            ],
        },
    }


class _FakeEmbedder:
    """Returns deterministic short vectors without calling OpenAI."""

    def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        return [EmbeddedChunk(**c.model_dump(), embedding=[0.1, 0.2, 0.3]) for c in chunks]


class _OkStore:
    """Store double that persists successfully and reports fixed ids."""

    def __init__(self, session=None) -> None:
        pass

    async def ingest_document(self, *, source_path, document_type, doc_metadata, chunks):
        return 42, len(chunks)


class _ConflictStore:
    """Store double that always reports the source_path as already ingested."""

    def __init__(self, session=None) -> None:
        pass

    async def ingest_document(self, *, source_path, document_type, doc_metadata, chunks):
        raise DocumentAlreadyExists(42)


async def _fake_async_session():
    yield None


@pytest.fixture
def ingest_client():
    app.dependency_overrides[get_embedder] = lambda: _FakeEmbedder()
    app.dependency_overrides[get_async_session] = _fake_async_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_ingest_persists_and_returns_metrics(ingest_client, monkeypatch):
    monkeypatch.setattr("app.api.embeddings.VectorStore", _OkStore)

    response = ingest_client.post("/embeddings/ingest", json=_budget_payload())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["document_id"] == 42
    assert body["chunks_created"] == 2  # one chunk per component (structural chunker)
    assert body["embedding_dimension"] == 1536
    assert isinstance(body["ingestion_time_ms"], int) and body["ingestion_time_ms"] >= 0


def test_ingest_duplicate_returns_flat_409(ingest_client, monkeypatch):
    monkeypatch.setattr("app.api.embeddings.VectorStore", _ConflictStore)

    response = ingest_client.post("/embeddings/ingest", json=_budget_payload())

    assert response.status_code == 409, response.text
    # Flat body (not nested under "detail") — the documented contract.
    assert response.json() == {"detail": "Document already ingested", "document_id": 42}


def test_ingest_without_embedder_returns_500(ingest_client):
    app.dependency_overrides[get_embedder] = lambda: None

    response = ingest_client.post("/embeddings/ingest", json=_budget_payload())

    assert response.status_code == 500


def test_ingest_rejects_invalid_budget(ingest_client, monkeypatch):
    monkeypatch.setattr("app.api.embeddings.VectorStore", _OkStore)
    payload = _budget_payload()
    payload["content"]["client_metadata"]["sector"] = "not_a_sector"  # violates Literal

    response = ingest_client.post("/embeddings/ingest", json=payload)

    assert response.status_code == 422
