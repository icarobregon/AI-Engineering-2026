"""Tests for the X-Correlation-ID middleware."""

import re

VALID_TRANSCRIPTION = (
    "El cliente necesita una landing page con formulario de contacto, "
    "integración con HubSpot, y blog con editor WYSIWYG. Plazo 4 semanas."
)


def test_correlation_id_echoed_when_provided(client):
    response = client.get("/health", headers={"X-Correlation-ID": "abc12345"})
    assert response.headers.get("x-correlation-id") == "abc12345"


def test_correlation_id_generated_when_missing(client):
    response = client.get("/health")
    correlation_id = response.headers.get("x-correlation-id")
    assert correlation_id is not None
    assert re.fullmatch(r"[0-9a-f]{8}", correlation_id), f"unexpected format: {correlation_id}"


def test_correlation_id_differs_between_requests(client):
    a = client.get("/health").headers["x-correlation-id"]
    b = client.get("/health").headers["x-correlation-id"]
    assert a != b


def test_correlation_id_present_on_estimate_endpoint(client, mock_llm):
    response = client.post(
        "/api/v1/estimate",
        json={"transcription": VALID_TRANSCRIPTION},
        headers={"X-Correlation-ID": "trace-001"},
    )
    assert response.status_code == 200
    assert response.headers.get("x-correlation-id") == "trace-001"


def test_correlation_id_present_on_validation_error(client):
    response = client.post(
        "/api/v1/estimate",
        json={},
        headers={"X-Correlation-ID": "trace-002"},
    )
    assert response.status_code == 422
    assert response.headers.get("x-correlation-id") == "trace-002"
