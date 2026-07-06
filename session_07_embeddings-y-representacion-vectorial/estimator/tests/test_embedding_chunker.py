"""Unit tests for the structural chunker (one component = one chunk)."""

from __future__ import annotations

import json
from pathlib import Path

import tiktoken

from app.embedding_pipeline.chunker import JSONStructuralChunker
from app.embedding_pipeline.schemas import Budget, IngestRequest
from tests.test_embedding_schemas import make_budget_dict

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "budgets_sample.json"


def _budgets(*dicts: dict) -> list[Budget]:
    return [Budget.model_validate(d) for d in dicts]


def test_one_chunk_per_component() -> None:
    budgets = _budgets(
        make_budget_dict(n_components=2),
        {**make_budget_dict(n_components=3), "budget_id": "BUD-T-002"},
    )
    chunks = JSONStructuralChunker().chunk(budgets)
    assert len(chunks) == 5


def test_chunk_id_format() -> None:
    chunks = JSONStructuralChunker().chunk(_budgets(make_budget_dict(n_components=1)))
    assert chunks[0].chunk_id == "BUD-T-001::C-0"


def test_metadata_keys_and_values() -> None:
    chunks = JSONStructuralChunker().chunk(_budgets(make_budget_dict(n_components=1)))
    meta = chunks[0].metadata
    assert set(meta) == {
        "budget_id",
        "component_id",
        "client_sector",
        "main_technology",
        "year",
        "complexity",
        "estimated_hours",
    }
    assert meta["client_sector"] == "finance"
    assert meta["main_technology"] == "python_fastapi"
    assert meta["complexity"] == "medium"
    assert meta["estimated_hours"] == 20


def test_text_has_context_header_and_component_fields() -> None:
    chunks = JSONStructuralChunker().chunk(_budgets(make_budget_dict(n_components=1)))
    text = chunks[0].text
    # Context header from the parent budget.
    assert "Test project summary" in text
    assert "finance" in text
    assert "2024" in text
    assert "python_fastapi" in text
    # Component fields.
    assert "Component 0" in text
    assert "Description of component 0" in text
    assert "medium" in text
    assert "postgresql" in text  # tech_stack joined


def test_token_count_matches_tiktoken() -> None:
    chunks = JSONStructuralChunker().chunk(_budgets(make_budget_dict(n_components=1)))
    encoding = tiktoken.encoding_for_model("text-embedding-3-small")
    assert chunks[0].token_count == len(encoding.encode(chunks[0].text))
    assert chunks[0].token_count > 0


def test_sample_dataset_chunks_completely() -> None:
    """Guards the professor's dataset: 60 components -> 60 unique chunks."""
    raw = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    budgets = IngestRequest.model_validate(raw).root
    chunks = JSONStructuralChunker().chunk(budgets)

    expected = sum(len(b.components) for b in budgets)
    assert len(chunks) == expected
    assert all(c.token_count > 0 for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)  # ids unique
