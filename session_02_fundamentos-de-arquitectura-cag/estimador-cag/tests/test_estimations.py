"""Tests for the /api/v1/estimate endpoint."""

import os
import glob
from unittest.mock import patch

VALID_TRANSCRIPTION = (
    "El cliente necesita una landing page con formulario de contacto, "
    "integración con HubSpot, y blog con editor WYSIWYG. Plazo 4 semanas."
)


def test_estimate_returns_200_and_payload(client, mock_llm):
    response = client.post(
        "/api/v1/estimate",
        json={"transcription": VALID_TRANSCRIPTION},
    )
    assert response.status_code == 200
    data = response.json()
    assert "estimation" in data
    assert "model" in data
    assert "provider" in data


def test_estimate_missing_transcription(client):
    response = client.post("/api/v1/estimate", json={})
    assert response.status_code == 422


def test_estimate_empty_transcription(client):
    response = client.post("/api/v1/estimate", json={"transcription": ""})
    assert response.status_code == 422


def test_estimate_short_transcription(client):
    response = client.post("/api/v1/estimate", json={"transcription": "short"})
    assert response.status_code == 422


def test_estimate_invalid_json(client):
    response = client.post(
        "/api/v1/estimate",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422


def test_estimate_calls_llm_service_once(client, mock_llm):
    client.post(
        "/api/v1/estimate",
        json={"transcription": VALID_TRANSCRIPTION},
    )
    mock_llm.assert_called_once_with(VALID_TRANSCRIPTION)


def test_estimate_llm_error_returns_500(client):
    with patch(
        "app.routers.estimations.generate_estimation",
        side_effect=RuntimeError("LLM unavailable"),
    ):
        response = client.post(
            "/api/v1/estimate",
            json={"transcription": VALID_TRANSCRIPTION},
        )
    assert response.status_code == 500


def test_swagger_docs_available(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_schema_available(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200


def test_env_not_hardcoded():
    src_dir = os.path.join(os.path.dirname(__file__), "..", "app")
    py_files = glob.glob(os.path.join(src_dir, "**", "*.py"), recursive=True)
    for path in py_files:
        with open(path) as f:
            content = f.read()
        assert "sk-" not in content, f"Possible hardcoded OpenAI key in {path}"
        assert "sk-ant-" not in content, f"Possible hardcoded Anthropic key in {path}"


def test_dotenv_in_gitignore():
    # Walk up from tests/ to find the nearest .gitignore (local or root-level)
    start = os.path.dirname(os.path.abspath(__file__))
    current = start
    gitignore_path = None
    for _ in range(6):
        candidate = os.path.join(current, ".gitignore")
        if os.path.isfile(candidate):
            gitignore_path = candidate
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    assert gitignore_path is not None, "No .gitignore found in any ancestor directory"
    with open(gitignore_path) as f:
        content = f.read()
    assert ".env" in content, f".env must be listed in {gitignore_path}"
