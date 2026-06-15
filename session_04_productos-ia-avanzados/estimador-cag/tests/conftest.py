"""Shared pytest fixtures."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app

MOCK_ESTIMATION = {
    "estimation": "## Mock\n| Phase | Duration | Cost |\n|---|---|---|\n| Build | 4w | 10,000 EUR |",
    "model": "gpt-4o-mini",
    "provider": "openai",
    "prompt_version": "v1",
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
