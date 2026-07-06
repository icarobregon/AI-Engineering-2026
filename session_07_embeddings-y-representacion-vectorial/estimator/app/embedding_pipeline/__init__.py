"""Session 7 — minimal embeddings & chunking pipeline.

Turns normalized JSON budgets into structural chunks (one component per chunk)
and embeds them with OpenAI ``text-embedding-3-small``. Nothing is persisted:
vectors are returned over HTTP. Vector storage (pgvector) arrives in Session 8.
"""
