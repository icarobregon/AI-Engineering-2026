"""Session 10 — full-text search column on chunks (lexical branch of hybrid search).

Revision ID: 0003_session10_fts
Revises: 0002_session8_pgvector
Create Date: 2026-08-17 00:00:00

Adds the lexical half of hybrid search: a generated ``content_tsv`` column over
``chunks.content`` plus its GIN index. The vector branch stays untouched — the
two run side by side in the same PostgreSQL and get fused by RRF, which is the
whole point of not adding a second datastore.

Two decisions worth defending:

* **Generated column, not a trigger.** ``GENERATED ALWAYS AS ... STORED`` makes
  PostgreSQL recompute the tsvector on every insert/update of ``content``. There
  is no application code and no trigger to keep in sync, so the lexical index
  physically cannot drift from the text it indexes.
* **GIN, not GiST.** GIN is the inverted index — slower to build, faster to
  query, and queries are what this column exists for.

**Text search configuration: 'english'.** The exercise statement says the budget
corpus is in Spanish. It is not: ``data/budgets_sample.json`` and
``data/task_corpus.json`` hold English component names and descriptions
("Faceted search", "Order lifecycle", "Product catalog model"); only client names
and the seed transcripts are Spanish. A Spanish analyser over English text would
leave English stop words ("with", "and", "for") in the vector and stem nothing
correctly, weakening the lexical branch precisely in the A/B/C/D measurement this
session exists to produce.

The literal below is deliberately hardcoded rather than imported from
``store.models.TEXT_SEARCH_CONFIG``: a migration is a record of what was applied
to the database at a point in time, and importing a constant would let a later
edit silently rewrite that history. The two must be changed together — and
changing them means a NEW migration that rebuilds the column, because a stored
tsvector is only as good as the configuration that built it.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_session10_fts"
down_revision: Union[str, None] = "0002_session8_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must stay in sync with app.generation.rag.store.models.TEXT_SEARCH_CONFIG.
TEXT_SEARCH_CONFIG = "english"


def upgrade() -> None:
    # Raw DDL: neither Alembic nor SQLAlchemy has a first-class helper for adding
    # a STORED generated column to an existing table.
    op.execute(
        "ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('{TEXT_SEARCH_CONFIG}', content)) STORED"
    )
    op.create_index(
        "ix_chunks_content_tsv",
        "chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_content_tsv", table_name="chunks")
    op.drop_column("chunks", "content_tsv")
