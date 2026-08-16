"""Session 9 — HNSW index over the halfvec cast of ``chunks.embedding``.

Revision ID: 0003_session9_hnsw
Revises: 0002_session8_pgvector
Create Date: 2026-08-16 00:00:00

The S08 live session built this index by hand (``scripts/sql_s08/``) so the
before/after could be measured. From S09 on it stops being a demo and becomes a
**precondition of the retriever**, so it belongs in a migration: a fresh
database must come up ready to serve retrieval, not sequential-scan silently.

Why the expression index and not ``hnsw (embedding vector_cosine_ops)``:
``ChunkStore.search`` ranks by ``cast(embedding, HALFVEC(1536)).cosine_distance(...)``,
which Postgres can only accelerate with an index built over that same
expression. A column index over ``embedding`` would be ignored — no error, no
warning, just a sequential scan. Operator class must be ``halfvec_cosine_ops``
to match the ``<=>`` operator the ORM emits.

Parameters (``m=16``, ``ef_construction=128``) are the S08 defaults: a good
graph for 1536 dimensions without a build time that hurts at this corpus size.
``ef_search`` is query-time and stays at the pgvector default (40).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0003_session9_hnsw"
down_revision: Union[str, None] = "0002_session8_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "chunks_embedding_halfvec_idx"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {INDEX_NAME}
        ON chunks
        USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
        WITH (m = 16, ef_construction = 128)
        """
    )
    # The planner will not choose the index until the table has fresh stats.
    op.execute("ANALYZE chunks")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
