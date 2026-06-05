"""Tests for the /api/v1/estimate/stream SSE endpoint."""

import json

VALID_TRANSCRIPTION = (
    "El cliente necesita una landing page con formulario de contacto, "
    "integración con HubSpot, y blog con editor WYSIWYG. Plazo 4 semanas."
)


def _parse_sse(body: str) -> list[dict]:
    """Parse SSE body into a list of {event, data} dicts (data is raw string)."""
    events = []
    current = {}
    for line in body.splitlines():
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif line.startswith("event:"):
            current["event"] = line[len("event:"):].lstrip(" ")
        elif line.startswith("data:"):
            value = line[len("data:"):]
            if value.startswith(" "):
                value = value[1:]
            current["data"] = value
    if current:
        events.append(current)
    return events


def test_stream_endpoint_returns_event_stream_content_type(client, mock_llm_stream):
    with client.stream(
        "POST",
        "/api/v1/estimate/stream",
        json={"transcription": VALID_TRANSCRIPTION},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        response.read()


def test_stream_endpoint_emits_delta_and_meta_events(client, mock_llm_stream):
    with client.stream(
        "POST",
        "/api/v1/estimate/stream",
        json={"transcription": VALID_TRANSCRIPTION},
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    delta_events = [e for e in events if e.get("event") == "delta"]
    meta_events = [e for e in events if e.get("event") == "meta"]

    assert [e["data"] for e in delta_events] == ["Hello ", "world"]
    assert len(meta_events) == 1
    meta = json.loads(meta_events[0]["data"])
    assert meta == {
        "model": "gpt-4o-mini",
        "provider": "openai",
        "tokens_in": 42,
        "tokens_out": 7,
        "finish_reason": "stop",
        "latency_ms": 123.4,
    }


def test_stream_endpoint_emits_error_event_on_llm_failure(client, monkeypatch):
    from app.routers import estimations as estimations_module

    def _fake_stream(_):
        yield {"type": "delta", "text": "partial..."}
        yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(estimations_module, "stream_estimation", _fake_stream)

    with client.stream(
        "POST",
        "/api/v1/estimate/stream",
        json={"transcription": VALID_TRANSCRIPTION},
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert {"event": "delta", "data": "partial..."} in events
    assert {"event": "error", "data": "boom"} in events


def test_stream_endpoint_rejects_invalid_transcription(client):
    response = client.post("/api/v1/estimate/stream", json={"transcription": "short"})
    assert response.status_code == 422


def test_stream_endpoint_echoes_correlation_id(client, mock_llm_stream):
    with client.stream(
        "POST",
        "/api/v1/estimate/stream",
        json={"transcription": VALID_TRANSCRIPTION},
        headers={"X-Correlation-ID": "trace-stream"},
    ) as response:
        response.read()
        assert response.headers.get("x-correlation-id") == "trace-stream"
