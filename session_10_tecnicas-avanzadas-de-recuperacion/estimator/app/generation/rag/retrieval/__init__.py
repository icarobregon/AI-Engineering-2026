"""Retrieval techniques layered on top of the Session 9 vector retriever.

* ``reranker`` — cross-encoder wrapper (model loading + query/document pair
  scoring). Given by the exercise; the recall width and the final cut are
  orchestration decisions that live outside it.
* ``verify_reranker`` — pre-flight script that checks the model downloads,
  loads and ranks a sanity pair correctly.

This package depends only on ``foundation`` + ``domain/schemas`` + sibling
modules under ``generation/rag`` — never on another ``generation`` family.
"""
