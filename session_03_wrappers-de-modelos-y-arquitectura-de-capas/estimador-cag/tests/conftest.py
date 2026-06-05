"""Shared pytest fixtures."""

import copy

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app

MOCK_ESTIMATION = {
    "estimation": "## Estimación\n1. Landing page: 20h - 2.000€\nTotal: 2.000€",
    "model": "gpt-4o-mini",
    "provider": "openai",
}


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def mock_llm():
    """Mock generate_estimation to avoid real LLM calls."""
    with patch(
        "app.routers.estimations.generate_estimation",
        return_value=MOCK_ESTIMATION,
    ) as mock:
        yield mock


MOCK_STREAM_EVENTS = [
    {"type": "delta", "text": "Hello "},
    {"type": "delta", "text": "world"},
    {
        "type": "meta",
        "model": "gpt-4o-mini",
        "provider": "openai",
        "tokens_in": 42,
        "tokens_out": 7,
        "finish_reason": "stop",
        "latency_ms": 123.4,
    },
]


@pytest.fixture
def mock_llm_stream():
    """Mock stream_estimation to avoid real LLM calls.

    Each call returns a fresh iterator over deep-copied events, so tests
    that consume the iterator and downstream code that mutates dicts (e.g.
    `.pop("type")`) don't leak state across tests.
    """
    def _fake_stream(_transcription):
        return iter(copy.deepcopy(MOCK_STREAM_EVENTS))

    with patch(
        "app.routers.estimations.stream_estimation",
        side_effect=_fake_stream,
    ) as mock:
        yield mock
