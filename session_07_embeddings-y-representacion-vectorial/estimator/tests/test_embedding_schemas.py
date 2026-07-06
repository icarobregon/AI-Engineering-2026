"""Unit tests for the embedding-pipeline Pydantic contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.embedding_pipeline.schemas import (
    Budget,
    Chunk,
    EmbeddedChunk,
    IngestRequest,
)


def make_budget_dict(*, sector: str = "finance", n_components: int = 1) -> dict:
    return {
        "budget_id": "BUD-T-001",
        "client_metadata": {"name": "TestCo", "sector": sector, "country": "ES"},
        "project_summary": "Test project summary",
        "main_technology": "python_fastapi",
        "year": 2024,
        "total_estimated_hours": 100,
        "components": [
            {
                "component_id": f"C-{i}",
                "name": f"Component {i}",
                "description": f"Description of component {i}",
                "tech_stack": ["python_fastapi", "postgresql"],
                "estimated_hours": 20,
                "complexity": "medium",
                "dependencies": [],
            }
            for i in range(n_components)
        ],
    }


def test_ingest_request_parses_bare_array() -> None:
    req = IngestRequest.model_validate([make_budget_dict(), make_budget_dict()])
    assert len(req.root) == 2
    assert all(isinstance(b, Budget) for b in req.root)


def test_invalid_sector_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Budget.model_validate(make_budget_dict(sector="banking"))


def test_invalid_complexity_is_rejected() -> None:
    data = make_budget_dict()
    data["components"][0]["complexity"] = "extreme"
    with pytest.raises(ValidationError):
        Budget.model_validate(data)


def test_budget_requires_at_least_one_component() -> None:
    data = make_budget_dict(n_components=0)
    with pytest.raises(ValidationError):
        Budget.model_validate(data)


def test_extra_fields_forbidden() -> None:
    data = make_budget_dict()
    data["components"][0]["unexpected"] = "nope"
    with pytest.raises(ValidationError):
        Budget.model_validate(data)


def test_embedded_chunk_extends_chunk() -> None:
    chunk = Chunk(chunk_id="a::b", text="hello", metadata={"k": "v"}, token_count=1)
    embedded = EmbeddedChunk(**chunk.model_dump(), embedding=[0.1, 0.2])
    assert isinstance(embedded, Chunk)
    assert embedded.chunk_id == "a::b"
    assert embedded.embedding == [0.1, 0.2]
