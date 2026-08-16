"""Pydantic models for the embedding pipeline.

Input side mirrors the normalized historical-budget JSON (a budget with a list
of components). Output side carries chunks ready to embed and, once embedded,
the vectors plus aggregate stats.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Closed universe of client sectors present in the sample dataset. Kept as a
# Literal so a typo or an unexpected sector fails validation loudly instead of
# silently leaking into the metadata.
Sector = Literal["finance", "ecommerce", "healthcare", "industrial"]
Complexity = Literal["low", "medium", "high"]


class ClientMetadata(BaseModel):
    """Who the budget belongs to. Travels as filterable context, not embedded."""

    name: str = Field(description="Client company name.")
    sector: Sector = Field(description="Client business sector.")
    country: str = Field(description="ISO-ish country code, e.g. 'ES'.")


class BudgetComponent(BaseModel):
    """A single line item of a historical budget."""

    component_id: str = Field(description="Stable id within the budget, e.g. 'AUTH-001'.")
    name: str = Field(description="Short human-readable component name.")
    description: str = Field(description="Detailed description of the work.")
    tech_stack: list[str] = Field(
        default_factory=list, description="Technologies involved in this component."
    )
    estimated_hours: int = Field(ge=0, description="Hours estimated for this component.")
    complexity: Complexity = Field(description="Coarse complexity bucket.")
    dependencies: list[str] = Field(
        default_factory=list, description="component_ids this one depends on."
    )


class Budget(BaseModel):
    """A complete historical budget with its components."""

    budget_id: str = Field(description="Stable budget id, e.g. 'BUD-2024-014'.")
    client_metadata: ClientMetadata
    project_summary: str = Field(description="One-line summary of the project.")
    main_technology: str = Field(description="Primary technology / stack of the project.")
    year: int = Field(ge=2000, le=2100, description="Year the budget was produced.")
    total_estimated_hours: int = Field(ge=0, description="Sum of component hours, as recorded.")
    components: list[BudgetComponent] = Field(min_length=1, description="Budget line items.")


class Chunk(BaseModel):
    """A fragment ready to be embedded.

    ``text`` is what gets sent to the embeddings API; ``metadata`` carries
    filterable fields that travel alongside the chunk but are NOT embedded.
    """

    chunk_id: str = Field(description="Traceable id, format '{budget_id}::{component_id}'.")
    text: str = Field(description="Embeddable text: parent context + component detail.")
    metadata: dict = Field(default_factory=dict, description="Filterable, non-embedded fields.")
    token_count: int = Field(ge=0, description="Token count of ``text`` (tiktoken).")


class EmbeddedChunk(Chunk):
    """A :class:`Chunk` with its embedding vector attached."""

    embedding: list[float] = Field(
        description="Dense embedding vector (1536 dims for text-embedding-3-small)."
    )


class IngestRequest(BaseModel):
    """Payload for ``POST /embeddings/ingest`` (Session 8: persisting contract).

    One request = one document. ``content`` is the full budget JSON, validated
    against :class:`Budget` so a malformed corpus fails with a 422 before
    touching the database or the embeddings API.
    """

    source_path: str = Field(
        min_length=1, description="Provenance of the document, unique per ingest."
    )
    document_type: str = Field(
        min_length=1, max_length=50, description="Document family, e.g. 'historical_budget'."
    )
    content: Budget = Field(description="Full budget JSON, as produced upstream.")


class IngestResponse(BaseModel):
    """Response for ``POST /embeddings/ingest``: identifiers + ingest metrics.

    Vectors no longer travel over HTTP — they are persisted in pgvector.
    """

    document_id: int = Field(description="Primary key of the persisted document.")
    chunks_created: int = Field(ge=0, description="Chunks persisted for this document.")
    embedding_dimension: int = Field(description="Dimensionality of the stored vectors.")
    ingestion_time_ms: int = Field(ge=0, description="Wall-clock ingest time.")


class SearchRequest(BaseModel):
    """Payload for ``POST /search``."""

    query: str = Field(min_length=1, description="Free-text semantic query.")
    k: int = Field(default=5, ge=1, le=50, description="Number of nearest chunks to return.")


class SearchHit(BaseModel):
    """One ranked chunk. ``chunk_id`` is the DB primary key; the traceable
    corpus id ('BUD-X::COMP-Y' parts) travels inside ``metadata``."""

    chunk_id: int
    document_id: int
    chunk_type: str
    content: str
    distance: float = Field(description="Cosine distance (lower = more similar).")
    metadata: dict


class SearchResponse(BaseModel):
    """Response for ``POST /search``."""

    query: str
    k: int
    search_time_ms: int = Field(ge=0)
    results: list[SearchHit]


# ---------------------------------------------------------------------------
# Session 9 — the RAG flow (query → retrieval → augmentation → generation)
# ---------------------------------------------------------------------------


class EstimationQuery(BaseModel):
    """Structured extraction of a raw meeting transcript.

    This is what the Query stage produces and what makes retrieval work: the
    transcript embedded whole is the centroid of every topic discussed, close
    to nothing in particular. Every field is either explicitly stated by the
    client or unambiguously inferable — see ``REFORMULATION_SYSTEM_PROMPT``.

    NOTE: no ``min_length``/``max_length`` constraints anywhere in this model.
    OpenAI structured outputs with ``strict: True`` reject most JSON Schema
    validation keywords, so constraints that matter are enforced by the prompt
    and, where they must hold, re-checked in Python.
    """

    function: str = Field(description="Primary product function in 3-7 words")
    technologies: list[str] = Field(
        default_factory=list,
        description="Specific technologies, services, or integrations mentioned",
    )
    sector: str | None = Field(
        default=None, description="Industry or vertical if explicitly mentioned"
    )
    scale: Literal["pilot", "small", "medium", "large"] | None = Field(
        default=None, description="Project scale if inferable from the conversation"
    )
    country: str | None = Field(default=None, description="Geographic scope if mentioned")
    regulations: list[str] = Field(
        default_factory=list,
        description="Regulatory frameworks mentioned (GDPR, BaFin, HIPAA, etc.)",
    )
    constraints: list[str] = Field(
        default_factory=list, description="Non-negotiable requirements or hard constraints"
    )


class ReformulationResult(BaseModel):
    """Output of the Query stage: what to embed, plus how we got there.

    ``query`` is ``None`` when the structured extraction failed and the plain
    rewriting fallback produced ``search_text``. Callers must treat that case
    as "no structural filters available", not as "no filters needed".
    """

    search_text: str = Field(description="The text actually sent to the embedder.")
    query: EstimationQuery | None = None
    used_fallback: bool = False


class RetrievedChunk(BaseModel):
    """A chunk that survived retrieval, flattened for the context assembler.

    ``sector``/``project_year``/``country`` are lifted out of the JSONB blob so
    the assembler and the citation validator never have to know how metadata is
    stored.
    """

    id: int
    content: str
    chunk_type: str
    distance: float = Field(description="Cosine distance (lower = more similar).")
    sector: str | None = None
    project_year: int | None = None
    country: str | None = None
    budget_id: str | None = None
    component_id: str | None = None
    main_technology: str | None = None

    @classmethod
    def from_row(cls, row) -> "RetrievedChunk":
        """Build from a ``ChunkStore.search`` row (metadata still as JSONB)."""
        meta = row.metadata_ or {}
        return cls(
            id=row.id,
            content=row.content,
            chunk_type=row.chunk_type,
            distance=float(row.distance),
            sector=meta.get("client_sector"),
            project_year=meta.get("year"),
            country=meta.get("country"),
            budget_id=meta.get("budget_id"),
            component_id=meta.get("component_id"),
            main_technology=meta.get("main_technology"),
        )


class RetrievalFilters(BaseModel):
    """Optional structural filters applied alongside vector similarity.

    All of them are ``None``-able on purpose: the SQL uses the
    ``(:filter IS NULL OR ...)`` idiom so one query shape serves every
    combination instead of building SQL by string concatenation.
    """

    sectors: list[str] | None = None
    countries: list[str] | None = None
    project_year_min: int | None = None
    project_year_max: int | None = None
    technologies: list[str] | None = None
    chunk_types: list[str] | None = None

    def is_empty(self) -> bool:
        return not any(self.model_dump().values())


class RetrievalResult(BaseModel):
    """Outcome of the Retrieval stage, including the soft-fail signal.

    ``low_confidence`` is the contract that stops the flow: when nothing beats
    the distance threshold, the orchestrator must NOT call the generator with
    an empty context — it reports back that the case needs manual review.
    """

    chunks: list[RetrievedChunk]
    low_confidence: bool
    total_candidates_considered: int
    search_time_ms: int


# --- HTTP contract for POST /v1/retrieval/search ---------------------------


class RetrievalSearchRequest(BaseModel):
    """Payload for ``POST /v1/retrieval/search``.

    Separate from the Session 8 ``SearchRequest`` (``POST /search``), which
    stays untouched as a public contract. This one exposes the production
    knobs: threshold and structural filters.
    """

    query_text: str = Field(min_length=10, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=30)
    distance_threshold: float = Field(default=0.6, ge=0.0, le=2.0)
    sectors: list[str] | None = None
    countries: list[str] | None = None
    project_year_min: int | None = Field(default=None, ge=2010, le=2100)
    project_year_max: int | None = Field(default=None, ge=2010, le=2100)
    technologies: list[str] | None = None
    chunk_types: list[str] | None = None

    def to_filters(self) -> RetrievalFilters:
        return RetrievalFilters(
            sectors=self.sectors,
            countries=self.countries,
            project_year_min=self.project_year_min,
            project_year_max=self.project_year_max,
            technologies=self.technologies,
            chunk_types=self.chunk_types,
        )


class RetrievalSearchResponse(BaseModel):
    """Response for ``POST /v1/retrieval/search``."""

    chunks: list[RetrievedChunk]
    low_confidence: bool
    total_candidates_considered: int
    search_time_ms: int
