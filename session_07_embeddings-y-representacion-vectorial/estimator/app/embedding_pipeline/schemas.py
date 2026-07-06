"""Pydantic v2 contract for the embeddings pipeline.

Input side (``Budget`` / ``BudgetComponent`` / ``ClientMetadata``) mirrors the
normalized budget JSON from Session 6. Output side (``Chunk`` /
``EmbeddedChunk``) is what the chunker and embedder produce. ``IngestRequest``
is a bare list of budgets so the sample dataset can be POSTed directly.

Nothing here is persisted; ``metadata`` on a chunk travels next to the vector,
ready to become pgvector filter columns in Session 8, and is deliberately kept
OUT of the embedded ``text``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, RootModel

# Closed vocabularies known from the project dataset. Kept as Literals so a
# malformed budget fails fast at validation instead of silently polluting the
# index. main_technology / tech_stack stay free-form (too many values).
Sector = Literal["finance", "ecommerce", "healthcare", "industrial"]
Complexity = Literal["low", "medium", "high"]


# --- Input: normalized budgets ---------------------------------------------


class ClientMetadata(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, description="Client display name.")
    sector: Sector = Field(description="Client industry sector.")
    country: str = Field(min_length=2, max_length=2, description="ISO-3166 alpha-2 country code.")


class BudgetComponent(BaseModel):
    model_config = {"extra": "forbid"}

    component_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tech_stack: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(ge=0)
    complexity: Complexity
    dependencies: list[str] = Field(default_factory=list)


class Budget(BaseModel):
    model_config = {"extra": "forbid"}

    budget_id: str = Field(min_length=1)
    client_metadata: ClientMetadata
    project_summary: str = Field(min_length=1)
    main_technology: str = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)
    total_estimated_hours: int = Field(ge=0)
    components: list[BudgetComponent] = Field(min_length=1)


# --- Output: chunks & embeddings -------------------------------------------


class Chunk(BaseModel):
    """A single embeddable unit: one budget component.

    ``text`` is what gets embedded (context header + component fields).
    ``metadata`` is NOT embedded — it rides alongside for future filtering.
    """

    chunk_id: str = Field(description="Stable id: '{budget_id}::{component_id}'.")
    text: str = Field(description="Embeddable text: context header + component fields.")
    metadata: dict = Field(description="Non-embedded filter metadata (S8 pgvector columns).")
    token_count: int = Field(ge=0, description="tiktoken count for text-embedding-3-small.")


class EmbeddedChunk(Chunk):
    embedding: list[float] = Field(description="Dense vector (1536 dims for text-embedding-3-small).")


# --- API request / response -------------------------------------------------


class IngestRequest(RootModel[list[Budget]]):
    """Request body is a bare JSON array of budgets (matches the sample file)."""


class IngestStats(BaseModel):
    total_budgets: int = Field(ge=0)
    total_chunks: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0.0)


class IngestResponse(BaseModel):
    chunks: list[EmbeddedChunk]
    stats: IngestStats
