"""The multi-agent estimation system (Sessions 13-14).

Session 13 turned a hand-written agent loop into an explicit graph: typed shared
state, one responsibility per node, edges that owned the control. Session 14
takes the control away from the edges and gives it to a supervisor, which is the
line between a workflow and an agentic system — not the number of nodes, but who
decides what happens next. A human gate can stop the run mid-flight and a
different process resumes it from the checkpoint.

This package sits at the CONDUCTOR level (``app/domain/``), which is the layer
allowed to compose siblings of ``generation`` — the same seat
``estimation_service.py`` occupies. Nothing above it changes: the service still
takes a transcript and returns a structured estimate with its ``status``.
"""
