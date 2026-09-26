"""Session 16 — production evaluation: golden set, harness and regression check.

Separate from the sibling ``evals`` modules on purpose. Those grade the
conversational path of Sessions 4-5 and the retrieval of Sessions 10-11, with
their own datasets and their own units (euros and weeks, relevance sets). This
package grades the DEPLOYED estimation service against historical hours, calls
the real model, and leaves a timestamped report behind so two runs can be
compared. Different question, different unit, different cadence.
"""
