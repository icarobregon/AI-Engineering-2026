"""Where a run stands, node by node, while it is still running.

This exists because the estimate stopped being a single blocking request. Once
the start verb answers 202 and the graph runs behind it, the only honest answer
to "how is it going?" has to be reconstructed from what is already persisted.

**The timeline comes from the checkpointer, not from the state.** There is not a
single timestamp anywhere in ``EstimationState``, so no duration can be derived
from it. The checkpointer, on the other hand, writes a snapshot per superstep and
stamps each one with ``created_at``. Attributing each snapshot to a node takes
one observation: LangGraph's checkpoint metadata carries no ``writes`` in this
version, but every snapshot knows what runs NEXT — so the node named by snapshot
N finished when snapshot N+1 was written.

That detail is what makes this feed worth having. ``routing_trail`` records
**dispatches**: its entry is written by the supervisor BEFORE the specialist
runs, so a feed built on it shows an agent as done for the whole time it is
actually working. This one reports **completions**, with the duration attached.

The failure marker is the other deliberate choice. A crashed background run
leaves ``next`` pointing at the node that died, which is indistinguishable from
a run still working on it. So the background task writes ``run_failed: …`` into
``errors`` — an accumulator, persisted like everything else — and that string,
never the shape of ``next``, is what makes a run read as failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TypedDict

RUN_FAILED_PREFIX = "run_failed: "

# The pseudo-node LangGraph puts in `next` for the input checkpoint. It is not a
# step anyone ran and showing it would put a phantom first row in every feed.
_START = "__start__"


class RunStep(TypedDict):
    """One superstep: a node, and how long it took."""

    node: str
    started_at: str
    finished_at: Optional[str]
    seconds: Optional[float]


def _elapsed(started_at: str, finished_at: str) -> Optional[float]:
    try:
        delta = datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        # A clock we cannot parse is reported as an unknown duration rather than
        # as zero: a zero reads like an instantaneous node, which is a lie a
        # dashboard will happily average.
        return None
    return round(delta.total_seconds(), 2)


def _failure(errors: list[str]) -> Optional[str]:
    for error in errors:
        if error.startswith(RUN_FAILED_PREFIX):
            return error[len(RUN_FAILED_PREFIX) :]
    return None


def build_timeline(snapshots: list) -> list[RunStep]:
    """The nodes that have run, oldest first, from the checkpoint history.

    ``snapshots`` is oldest-first. Each one contributes the node it was about to
    run, closed off by the timestamp of the one after it; the last snapshot's
    node is the one still in flight and has no ``finished_at``.
    """
    steps: list[RunStep] = []
    for index, snapshot in enumerate(snapshots):
        pending = list(getattr(snapshot, "next", None) or ())
        if not pending or pending[0] == _START:
            continue

        started_at = getattr(snapshot, "created_at", None) or ""
        siguiente = snapshots[index + 1] if index + 1 < len(snapshots) else None
        finished_at = getattr(siguiente, "created_at", None) if siguiente else None

        # A superstep can fan out to several nodes. One row each, sharing the
        # window: pretending the first one owns it would understate the rest.
        for node in pending:
            steps.append(
                RunStep(
                    node=node,
                    started_at=started_at,
                    finished_at=finished_at,
                    seconds=_elapsed(started_at, finished_at) if finished_at else None,
                )
            )
    return steps


def build_progress(snapshots: list, *, review_payload: Optional[dict] = None) -> dict:
    """The full progress report for one run.

    ``snapshots`` is the checkpoint history, oldest first. ``review_payload`` is
    the pending interrupt's payload, which the caller already has to read to know
    whether the run is waiting on a human.
    """
    latest = snapshots[-1] if snapshots else None
    values = dict(getattr(latest, "values", None) or {})
    pending = list(getattr(latest, "next", None) or ())
    errors = list(values.get("errors") or [])
    steps = build_timeline(snapshots)

    failure = _failure(errors)
    if review_payload:
        status = "awaiting_human_review"
    elif failure:
        status = "failed"
    elif values and not pending:
        status = "finished"
    else:
        status = "running"

    # Only a run that is actually working has something in flight. A paused or
    # crashed thread also has a non-empty `next`, and reporting its node as
    # "current" is how a stuck run gets read as a busy one.
    current = pending[0] if status == "running" and pending else None

    return {
        "status": status,
        "current": current,
        "failure": failure,
        "steps": steps,
        "counts": {
            "requirements": len(values.get("requirements") or []),
            "components": len(values.get("components") or []),
            "budget_matches": len(values.get("budget_matches") or []),
            "routing_steps": values.get("routing_steps") or 0,
            "has_estimate": values.get("estimate") is not None,
            "confidence": values.get("confidence"),
        },
        # The run's own errors, with the internal failure marker filtered out:
        # it is reported as `failure`, and showing it twice in two shapes invites
        # a UI to print the same problem in two places.
        "errors": [e for e in errors if not e.startswith(RUN_FAILED_PREFIX)],
        "routing_trail": list(values.get("routing_trail") or []),
        "last_activity_at": getattr(latest, "created_at", None) if latest else None,
        "review_payload": review_payload,
    }
