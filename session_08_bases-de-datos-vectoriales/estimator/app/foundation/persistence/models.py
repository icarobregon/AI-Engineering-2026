"""SQLAlchemy ORM models.

Session 6 tables (both narrow and write-rare):

* ``pseudonym_mappings`` — the GDPR-grade reversible mapping for PII. Keyed by
  ``(entity_type, original_hash)``; the hash is HMAC-SHA256 over the original
  value with a server-side salt. Storing the hash (not the plaintext) means a
  read of the DB alone cannot reconstruct the original — that is the property
  that makes Art. 17 "right to be forgotten" auditable.

* ``ingestion_jobs`` — book-keeping for the asynchronous ``POST /ingestion/runs``
  endpoint. A row is created when the request hits, a BackgroundTask updates it
  to ``running``/``completed``/``failed``. The ``GET /ingestion/jobs/{id}``
  endpoint reads from here.

Session 8 tables (the vector layer):

* ``documents`` / ``chunks`` — an ingested budget becomes one ``documents`` row
  with N ``chunks`` (one per component), each carrying its 1536-dim embedding.
  One-to-many with ``ON DELETE CASCADE``. See the schema-rationale section in
  ``README.md`` for why two tables, JSONB metadata and no vector index yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime

# Dimensionality of text-embedding-3-small. Hardcoded on purpose: changing it
# would mean re-embedding the whole corpus, so it is not a runtime knob.
EMBEDDING_DIM = 1536


class Base(DeclarativeBase):
    """Single declarative base — picked up by Alembic env.py."""


class PseudonymMappingRow(Base):
    __tablename__ = "pseudonym_mappings"
    __table_args__ = (
        UniqueConstraint("entity_type", "original_hash", name="uq_mappings_entity_hash"),
        Index("idx_mappings_lookup", "entity_type", "original_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    original_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    pseudonym: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IngestionJobRow(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (Index("idx_jobs_status", "status"),)

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    documents_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentRow(Base):
    """One ingested source document (a historical budget)."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # ``metadata`` is reserved by DeclarativeBase for the MetaData object, so the
    # Python attribute is ``meta`` while the DB column keeps the name ``metadata``.
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )


class ChunkRow(Base):
    """A single embeddable fragment of a document (one budget component)."""

    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_chunk_type", "chunk_type"),
        Index("ix_chunks_metadata_gin", "metadata", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable so a chunk can be created and embedded later (async ingestion in
    # later sessions); this exercise always fills it in the same transaction.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    meta: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
