"""HTTP tests for the two Session 9 surfaces: auth, limits, contracts.

No OpenAI and no Postgres: the retriever and the conductor are overridden with
doubles. What is under test is the service layer — who gets in, what a rejected
caller sees, and whether the contracts hold.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import get_estimation_service, get_semantic_retriever
from app.domain.schemas.rag_estimate import (
    Assumption,
    CostComponent,
    Estimate,
    EstimateResponse,
    RetrievalTrace,
    SourceCitation,
)
from app.generation.rag.schemas import RetrievalResult, RetrievedChunk
from app.main import app
from app.rate_limit import limiter

RETRIEVAL_KEY = "retrieval-test-key"
ESTIMATE_KEY = "estimate-test-key"
TRANSCRIPT = "Reunión con el cliente sobre un marketplace multi-vendedor. " * 5


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def configured_keys(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_API_KEY", RETRIEVAL_KEY)
    monkeypatch.setenv("ESTIMATE_API_KEY", ESTIMATE_KEY)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeRetriever:
    def __init__(self, chunks=None) -> None:
        self.chunks = chunks if chunks is not None else [
            RetrievedChunk(
                id=21,
                content="Component: Split order management",
                chunk_type="budget_component",
                distance=0.3936,
                sector="ecommerce",
                project_year=2023,
                country="DE",
                budget_id="BUD-2024-006",
                component_id="ORDER-002",
            )
        ]
        self.calls: list[dict] = []

    async def retrieve(self, **kwargs) -> RetrievalResult:
        self.calls.append(kwargs)
        return RetrievalResult(
            chunks=self.chunks,
            low_confidence=not self.chunks,
            total_candidates_considered=32,
            search_time_ms=8,
        )


class FakeService:
    def __init__(self, response: EstimateResponse | None = None) -> None:
        self.response = response or make_estimate_response()
        self.calls: list[dict] = []

    async def estimate_from_transcript(self, transcript, idempotency_key=None):
        self.calls.append({"transcript": transcript, "idempotency_key": idempotency_key})
        return self.response


def make_estimate_response(**overrides) -> EstimateResponse:
    base = dict(
        request_id="abc123",
        estimate=Estimate(
            total_engineer_days=68,
            cost_breakdown=[CostComponent(name="Payouts", engineer_days=68, sources=[21])],
            duration_weeks=9,
            sources=[SourceCitation(source_id=21, relevance="primary", used_for="Payouts")],
            assumptions=[Assumption(description="No app", impact="low", rationale="n/a")],
            confidence="medium",
            reasoning="Based on source 21.",
        ),
        low_confidence=False,
        needs_manual_review=False,
        retrieval=RetrievalTrace(
            chunks_retrieved=4, chunks_used=4, total_candidates_considered=32
        ),
    )
    return EstimateResponse(**{**base, **overrides})


@pytest.fixture
def client(configured_keys):
    retriever = FakeRetriever()
    service = FakeService()
    app.dependency_overrides[get_semantic_retriever] = lambda: retriever
    app.dependency_overrides[get_estimation_service] = lambda: service
    with TestClient(app) as c:
        c.fake_retriever = retriever
        c.fake_service = service
        yield c
    app.dependency_overrides.clear()


# --- retrieval surface ------------------------------------------------------


def test_search_requires_an_api_key(client):
    response = client.post("/v1/retrieval/search", json={"query_text": "marketplace payouts"})
    assert response.status_code == 422  # missing required header


def test_search_rejects_a_wrong_key(client):
    response = client.post(
        "/v1/retrieval/search",
        json={"query_text": "marketplace payouts"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid API key"


def test_search_rejects_the_other_surfaces_key(client):
    """The whole point of two keys: one must not open the other's door."""
    response = client.post(
        "/v1/retrieval/search",
        json={"query_text": "marketplace payouts"},
        headers={"X-API-Key": ESTIMATE_KEY},
    )
    assert response.status_code == 401


def test_search_returns_chunks_and_the_confidence_signal(client):
    response = client.post(
        "/v1/retrieval/search",
        json={"query_text": "multi-vendor marketplace with payouts", "top_k": 5},
        headers={"X-API-Key": RETRIEVAL_KEY},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["low_confidence"] is False
    assert body["total_candidates_considered"] == 32
    assert body["chunks"][0]["id"] == 21
    assert body["chunks"][0]["distance"] == 0.3936


def test_search_passes_filters_through_to_the_retriever(client):
    client.post(
        "/v1/retrieval/search",
        json={
            "query_text": "multi-vendor marketplace",
            "sectors": ["ecommerce"],
            "project_year_min": 2023,
            "distance_threshold": 0.55,
            "top_k": 7,
        },
        headers={"X-API-Key": RETRIEVAL_KEY},
    )
    call = client.fake_retriever.calls[0]
    assert call["top_k"] == 7
    assert call["distance_threshold"] == 0.55
    assert call["filters"].sectors == ["ecommerce"]
    assert call["filters"].project_year_min == 2023


def test_search_validates_its_bounds_before_any_io(client):
    response = client.post(
        "/v1/retrieval/search",
        json={"query_text": "short", "top_k": 99},
        headers={"X-API-Key": RETRIEVAL_KEY},
    )
    assert response.status_code == 422
    assert client.fake_retriever.calls == []


def test_empty_retrieval_is_a_200_with_low_confidence(configured_keys):
    app.dependency_overrides[get_semantic_retriever] = lambda: FakeRetriever(chunks=[])
    with TestClient(app) as c:
        response = c.post(
            "/v1/retrieval/search",
            json={"query_text": "quantum blockchain for cattle"},
            headers={"X-API-Key": RETRIEVAL_KEY},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["low_confidence"] is True
    assert response.json()["chunks"] == []


# --- estimate surface -------------------------------------------------------


def test_estimate_rejects_the_retrieval_key(client):
    response = client.post(
        "/v1/estimate/from-transcript",
        json={"transcript": TRANSCRIPT},
        headers={"X-API-Key": RETRIEVAL_KEY},
    )
    assert response.status_code == 401


def test_estimate_returns_the_envelope_and_the_request_id_header(client):
    response = client.post(
        "/v1/estimate/from-transcript",
        json={"transcript": TRANSCRIPT, "idempotency_key": "key-1"},
        headers={"X-API-Key": ESTIMATE_KEY},
    )
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "abc123"
    body = response.json()
    assert body["estimate"]["total_engineer_days"] == 68
    assert body["retrieval"]["chunks_used"] == 4
    assert client.fake_service.calls[0]["idempotency_key"] == "key-1"


def test_estimate_rejects_a_transcript_too_short_to_be_one(client):
    response = client.post(
        "/v1/estimate/from-transcript",
        json={"transcript": "hola"},
        headers={"X-API-Key": ESTIMATE_KEY},
    )
    assert response.status_code == 422
    assert client.fake_service.calls == []


def test_low_confidence_estimate_is_a_200_not_an_error(configured_keys):
    response_body = make_estimate_response(
        estimate=None,
        low_confidence=True,
        needs_manual_review=True,
        review_reason="No historical chunk passed the distance threshold (0.6)",
    )
    app.dependency_overrides[get_estimation_service] = lambda: FakeService(response_body)
    with TestClient(app) as c:
        response = c.post(
            "/v1/estimate/from-transcript",
            json={"transcript": TRANSCRIPT},
            headers={"X-API-Key": ESTIMATE_KEY},
        )
    app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["estimate"] is None
    assert body["needs_manual_review"] is True
    assert "distance threshold" in body["review_reason"]


# --- rate limiting ----------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ESTIMATE", "2/minute")
    get_settings.cache_clear()

    payload = {"transcript": TRANSCRIPT}
    headers = {"X-API-Key": ESTIMATE_KEY}
    assert client.post("/v1/estimate/from-transcript", json=payload, headers=headers).status_code == 200
    assert client.post("/v1/estimate/from-transcript", json=payload, headers=headers).status_code == 200

    third = client.post("/v1/estimate/from-transcript", json=payload, headers=headers)
    assert third.status_code == 429
    assert third.headers["Retry-After"] == "60"
    body = third.json()
    assert body["error"] == "rate_limit_exceeded"
    assert body["retry_after_seconds"] == 60
    get_settings.cache_clear()


def test_the_two_surfaces_have_independent_budgets(client, monkeypatch):
    """Exhausting the estimate quota must not throttle retrieval."""
    monkeypatch.setenv("RATE_LIMIT_ESTIMATE", "1/minute")
    get_settings.cache_clear()

    client.post(
        "/v1/estimate/from-transcript",
        json={"transcript": TRANSCRIPT},
        headers={"X-API-Key": ESTIMATE_KEY},
    )
    blocked = client.post(
        "/v1/estimate/from-transcript",
        json={"transcript": TRANSCRIPT},
        headers={"X-API-Key": ESTIMATE_KEY},
    )
    still_open = client.post(
        "/v1/retrieval/search",
        json={"query_text": "multi-vendor marketplace"},
        headers={"X-API-Key": RETRIEVAL_KEY},
    )

    assert blocked.status_code == 429
    assert still_open.status_code == 200
    get_settings.cache_clear()


# --- unconfigured server ----------------------------------------------------


def test_unconfigured_key_is_a_503_not_an_open_door(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.api.security.get_settings",
        lambda: type("S", (), {"RETRIEVAL_API_KEY": None, "ESTIMATE_API_KEY": None})(),
    )
    with TestClient(app) as c:
        response = c.post(
            "/v1/retrieval/search",
            json={"query_text": "multi-vendor marketplace"},
            headers={"X-API-Key": "anything"},
        )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
