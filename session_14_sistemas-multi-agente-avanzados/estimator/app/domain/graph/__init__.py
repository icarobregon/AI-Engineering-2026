"""Graph orchestration for the estimation flow (Session 13).

The Session 12 agent decided its own control flow inside a hand-written loop.
Here the same work is expressed as an explicit LangGraph: typed shared state,
one responsibility per node, edges that own the control, a checkpoint after every
step and a span per node.

This package sits at the CONDUCTOR level (``app/domain/``), which is the layer
allowed to compose siblings of ``generation`` — the same seat
``estimation_service.py`` occupies. Nothing above it changes: the service still
takes a transcript and returns a structured estimate with its ``status``.
"""
