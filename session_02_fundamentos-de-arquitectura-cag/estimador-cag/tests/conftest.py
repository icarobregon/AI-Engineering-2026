"""Shared pytest fixtures."""

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
