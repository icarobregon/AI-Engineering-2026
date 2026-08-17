"""SQLAlchemy ORM models for the vector store (Session 8).

Two tables, a real one-to-many:

* ``documents`` — one row per ingested source (a historical budget). Owns
  provenance: where it came from, when, and document-level metadata.
* ``chunks`` — N rows per document, each carrying the embeddable text and its
  1536-dim vector. ``ON DELETE CASCADE`` means deleting a budget removes all
  its chunks — referential integrity instead of denormalized duplication.

Design notes (defended in the README):

* ``metadata`` is a JSONB column on both tables. Stable fields live in typed
  columns; whatever the chunker enriches (sector, technologies, hours) goes to
  JSONB, queryable via the GIN index without a migration per new key.
* ``embedding`` is **nullable**: it allows inserting a chunk first and filling
  the vector later (async ingestion, future sessions). Session 8 ingests
  chunk+embedding atomically and never exercises that path.
* ``Vector(1536)`` is hardcoded to ``text-embedding-3-small``'s dimensionality;
  changing it means re-embedding the whole corpus, so it is not configuration.
* **No vector index on purpose** — the live session adds HNSW and measures the
  before/after against this sequential-scan baseline.

``metadata`` is a reserved attribute on SQLAlchemy declarative models, so the
Python attribute is ``metadata_`` mapped onto the ``"metadata"`` column.
"""

from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

from app.foundation.persistence.models import Base

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small

# PostgreSQL text search configuration for the lexical branch. It fixes the
# stemming rules and the stop-word list, and BOTH sides must agree: a tsvector
# built with one configuration and queried with another silently under-matches.
# Every lexical query imports this constant instead of inlining a literal.
#
# 'english' — not 'spanish' — because that is the language the corpus is actually
# written in: data/budgets_sample.json and data/task_corpus.json hold English
# component names and descriptions ("Faceted search", "Order lifecycle",
# "Product catalog model"). Only client names and the seed transcripts are in
# Spanish. The exercise statement says the budgets are in Spanish; they are not,
# and a Spanish analyser over English text would neither strip English stop words
# nor stem correctly, which would understate the lexical branch in exactly the
# A/B/C/D comparison this session has to measure.
#
# Changing this value requires a new migration that rebuilds the generated
# column — the stored tsvector is only as good as the configuration that built it.
TEXT_SEARCH_CONFIG = "english"


class DocumentRow(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_source_path", "source_path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    chunks: Mapped[list[ChunkRow]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class ChunkRow(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_chunk_type", "chunk_type"),
        Index("ix_chunks_metadata_gin", "metadata", postgresql_using="gin"),
        # Inverted index over the tsvector — the structure that makes the lexical
        # branch a lookup instead of a scan.
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Lexical index payload: `content` tokenized, lowercased, stop-worded and
    # stemmed. GENERATED ALWAYS ... STORED, so PostgreSQL recomputes it on every
    # insert/update of `content` — no trigger to maintain and no way for the
    # lexical index to drift from the text it indexes. Read-only from the app
    # (SQLAlchemy excludes Computed columns from INSERT/UPDATE); nullable because
    # the DDL adds no NOT NULL, though in practice it is never null.
    content_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{TEXT_SEARCH_CONFIG}', content)", persisted=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")
