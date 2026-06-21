"""Integration tests for the conversational session endpoints.

Tests run against the real FastAPI app via httpx.AsyncClient + ASGITransport.
LLM calls are mocked at the ConversationService boundary to avoid real network
calls and keep the suite fast.

FastAPI resolves dependencies through its own DI container, so we use
``app.dependency_overrides`` (not unittest.mock.patch on the module name)
to inject test doubles.

Three required tests (Paso 7 of the Session 5 exercise):

1. Two linked requests in the same session verify that project_metadata is
   updated between turns.
2. A request with a PDF attachment verifies that the document text reaches the
   enriched description passed to the service.
3. Eight turns to the same session verify that the history never exceeds
   MAX_TURNS pairs.
"""

from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_conversation_service, get_session_store
from app.main import app
from app.schemas.estimation import EstimationResult, Phase
from app.sessions import ProjectMetadata, SessionStore

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_PHASES = [
    Phase(name="Discovery", duration_weeks=1, cost_eur=5000, summary="Scope and planning."),
    Phase(name="Build", duration_weeks=3, cost_eur=15000, summary="Implementation phase."),
]

_MOCK_RESULT = EstimationResult(
    summary="A solid project with clear scope.",
    confidence_pct=75,
    phases=_VALID_PHASES,
    total_duration_weeks=4,
    total_cost_eur=20000,
)

_BASE_FORM = {
    "description": "We need a web SaaS for managing restaurant reservations, with React frontend.",
    "project_type": "web_saas",
    "detail_level": "medium",
    "output_format": "phases_table",
}


# ---------------------------------------------------------------------------
# Helper: override FastAPI dependencies for the duration of a test
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _override(overrides: dict):
    """Context manager: install dependency overrides, then remove them."""
    app.dependency_overrides.update(overrides)
    try:
        yield
    finally:
        for key in overrides:
            app.dependency_overrides.pop(key, None)


def _make_simple_conversation_service(store: SessionStore):
    """A mock ConversationService whose estimate() appends to history and
    returns a valid ConversationEstimateResponse without calling the LLM."""

    def fake_estimate(session, request, attachments):
        from app.attachments import build_enriched_description
        from app.schemas.conversation import ConversationEstimateResponse

        # Record the enriched description (used in test 2).
        enriched = build_enriched_description(request.description, attachments)
        fake_estimate.last_enriched_description = enriched

        session.history.append(
            user_content=enriched,
            assistant_content="Mock assistant response.",
        )
        return ConversationEstimateResponse(
            result=_MOCK_RESULT,
            prompt_version="v2",
            cached=False,
            project_metadata=session.project_metadata,
            turn=session.history.turn_count,
        )

    fake_estimate.last_enriched_description = ""
    mock = MagicMock()
    mock.estimate.side_effect = fake_estimate
    return mock


async def _create_session(client: AsyncClient) -> str:
    resp = await client.post("/sessions")
    assert resp.status_code == 201, resp.text
    return resp.json()["session_id"]


async def _estimate(client: AsyncClient, session_id: str, **form_overrides) -> dict:
    form = {**_BASE_FORM, **form_overrides}
    resp = await client.post(f"/sessions/{session_id}/estimate", data=form)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Test 1 — ProjectMetadata updates between turns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_project_metadata_updates_between_turns():
    """Two linked requests in the same session: metadata accumulates across turns."""
    store = SessionStore(max_turns=6)

    # Metadata updates that the mock service will inject on each turn.
    turn1_update = ProjectMetadata(
        project_name="BookFlow",
        mentioned_technologies=["React", "PostgreSQL"],
    )
    turn2_update = ProjectMetadata(
        assumed_team_size=3,
        mentioned_technologies=["AWS"],
        explicit_constraints=["Budget under 30k EUR"],
    )
    updates = [turn1_update, turn2_update]
    call_count = {"n": 0}

    def fake_estimate_with_metadata(session, request, attachments):
        from app.attachments import build_enriched_description
        from app.schemas.conversation import ConversationEstimateResponse

        idx = call_count["n"]
        call_count["n"] += 1

        # Apply the metadata update for this call.
        if idx < len(updates):
            session.project_metadata = session.project_metadata.merge(updates[idx])

        session.history.append(
            user_content=request.description,
            assistant_content="Mock assistant response.",
        )
        return ConversationEstimateResponse(
            result=_MOCK_RESULT,
            prompt_version="v2",
            cached=False,
            project_metadata=session.project_metadata,
            turn=session.history.turn_count,
        )

    mock_service = MagicMock()
    mock_service.estimate.side_effect = fake_estimate_with_metadata

    with _override({
        get_session_store: lambda: store,
        get_conversation_service: lambda: mock_service,
    }):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            session_id = await _create_session(client)

            # Turn 1.
            body1 = await _estimate(
                client, session_id,
                description="We are building BookFlow, a SaaS with React and PostgreSQL.",
            )
            meta1 = body1["project_metadata"]
            assert meta1["project_name"] == "BookFlow"
            assert "React" in meta1["mentioned_technologies"]
            assert body1["turn"] == 1

            # Turn 2.
            body2 = await _estimate(
                client, session_id,
                description="Team is 3 people, budget under 30k EUR, deploying on AWS.",
            )
            meta2 = body2["project_metadata"]
            # Scalar from turn 1 survives.
            assert meta2["project_name"] == "BookFlow"
            # New scalar from turn 2.
            assert meta2["assumed_team_size"] == 3
            # Lists are merged across turns.
            assert "React" in meta2["mentioned_technologies"]
            assert "AWS" in meta2["mentioned_technologies"]
            assert "Budget under 30k EUR" in meta2["explicit_constraints"]
            assert body2["turn"] == 2


# ---------------------------------------------------------------------------
# Test 2 — PDF attachment text reaches the service
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pdf_attachment_text_reaches_service():
    """Uploading a PDF results in its extracted text being included in the
    enriched description passed to ConversationService.estimate()."""
    store = SessionStore(max_turns=6)
    received: list[str] = []

    def capturing_estimate(session, request, attachments):
        from app.attachments import build_enriched_description
        from app.schemas.conversation import ConversationEstimateResponse

        enriched = build_enriched_description(request.description, attachments)
        received.append(enriched)

        session.history.append(user_content=request.description, assistant_content="ok")
        return ConversationEstimateResponse(
            result=_MOCK_RESULT,
            prompt_version="v2",
            cached=False,
            project_metadata=session.project_metadata,
            turn=session.history.turn_count,
        )

    mock_service = MagicMock()
    mock_service.estimate.side_effect = capturing_estimate

    pdf_text = "This project requires Kubernetes and a microservices architecture."
    pdf_bytes = _make_minimal_pdf(pdf_text)

    with _override({
        get_session_store: lambda: store,
        get_conversation_service: lambda: mock_service,
    }):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            session_id = await _create_session(client)

            resp = await client.post(
                f"/sessions/{session_id}/estimate",
                data=_BASE_FORM,
                files=[("files", ("spec.pdf", pdf_bytes, "application/pdf"))],
            )
            assert resp.status_code == 200, resp.text

    assert received, "ConversationService.estimate() was never called"
    enriched = received[0]
    # The attachment separator must appear.
    assert "--- attachment: spec.pdf ---" in enriched
    # A distinctive word from the PDF must be present.
    assert "Kubernetes" in enriched or "microservices" in enriched


# ---------------------------------------------------------------------------
# Test 3 — History never exceeds MAX_TURNS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_never_exceeds_max_turns():
    """Sending 8 turns to a session configured with MAX_TURNS=6 must keep the
    history at most 6 pairs at any point after the limit is reached."""
    from app.config import get_settings

    max_turns = get_settings().MAX_TURNS  # 6 by default
    store = SessionStore(max_turns=max_turns)

    def minimal_estimate(session, request, attachments):
        from app.schemas.conversation import ConversationEstimateResponse

        session.history.append(
            user_content=request.description,
            assistant_content="ok",
        )
        return ConversationEstimateResponse(
            result=_MOCK_RESULT,
            prompt_version="v2",
            cached=False,
            project_metadata=session.project_metadata,
            turn=session.history.turn_count,
        )

    mock_service = MagicMock()
    mock_service.estimate.side_effect = minimal_estimate

    with _override({
        get_session_store: lambda: store,
        get_conversation_service: lambda: mock_service,
    }):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            session_id = await _create_session(client)
            session = store.get(session_id)
            assert session is not None

            for i in range(8):
                await _estimate(
                    client, session_id,
                    description=f"Turn {i + 1}: adding more requirements to the project scope here.",
                )
                assert session.history.turn_count <= max_turns, (
                    f"After turn {i + 1}, history has {session.history.turn_count} pairs "
                    f"but MAX_TURNS={max_turns}"
                )

        # After 8 turns with MAX_TURNS=6, exactly max_turns pairs are kept.
        assert session.history.turn_count == max_turns


# ---------------------------------------------------------------------------
# Additional smoke tests (synchronous, no LLM needed)
# ---------------------------------------------------------------------------

def test_create_session_returns_uuid():
    """POST /sessions returns a valid UUID string."""
    import re
    from fastapi.testclient import TestClient

    store = SessionStore(max_turns=6)
    with _override({get_session_store: lambda: store}):
        client = TestClient(app)
        resp = client.post("/sessions")
        assert resp.status_code == 201
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        )
        assert uuid_re.match(resp.json()["session_id"])


def test_estimate_unknown_session_returns_404():
    """POST /sessions/{id}/estimate with a non-existent session_id returns 404."""
    from fastapi.testclient import TestClient

    store = SessionStore(max_turns=6)
    with _override({get_session_store: lambda: store}):
        client = TestClient(app)
        resp = client.post(
            "/sessions/00000000-0000-0000-0000-000000000000/estimate",
            data=_BASE_FORM,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Minimal PDF builder (no external deps beyond stdlib)
# ---------------------------------------------------------------------------

def _make_minimal_pdf(text: str) -> bytes:
    """Build a minimal PDF containing *text* using only stdlib.

    Hand-crafted PDF 1.4 structure sufficient for pypdf to extract the text.
    """
    safe_text = text.replace("\\", "\\\\").replace("(", r"\(").replace(")", r"\)")
    stream_content = f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)

    def obj(n: int, body: str) -> bytes:
        return f"{n} 0 obj\n{body}\nendobj\n".encode()

    objs = [
        obj(1, "<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(
            3,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
            " /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        obj(4, f"<< /Length {stream_len} >>\nstream\n{stream_content}\nendstream"),
        obj(5, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]

    header = b"%PDF-1.4\n"
    body_bytes = b"".join(objs)
    xref_offset = len(header) + len(body_bytes)

    offsets: list[int] = []
    pos = len(header)
    for o in objs:
        offsets.append(pos)
        pos += len(o)

    xref = b"xref\n" + f"0 {len(objs) + 1}\n".encode()
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return header + body_bytes + xref + trailer
