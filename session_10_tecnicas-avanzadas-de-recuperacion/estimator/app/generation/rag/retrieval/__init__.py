"""Retrieval techniques layered on top of the Session 9 vector retriever.

* ``fulltext_search`` — lexical branch over the generated ``content_tsv`` column.
* ``fusion`` — Reciprocal Rank Fusion; combines rankings by position, not score.
* ``hybrid_search`` — runs the semantic and lexical branches concurrently and
  fuses them into one ranking.
* ``reranker`` — cross-encoder wrapper (model loading + query/document pair
  scoring). Given by the exercise; the recall width and the final cut are
  orchestration decisions that live outside it.
* ``verify_reranker`` — pre-flight script that checks the model downloads,
  loads and ranks a sanity pair correctly.
* ``pipeline`` — the single ``retrieve()`` entrypoint that composes the four
  configurations behind the ``search_mode`` and ``rerank`` switches.

This package depends only on ``foundation`` + ``domain/schemas`` + sibling
modules under ``generation/rag`` — never on another ``generation`` family.
"""
