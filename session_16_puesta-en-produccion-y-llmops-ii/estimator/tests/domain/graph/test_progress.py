"""The progress feed, derived from the checkpoint history.

These tests defend three claims that are easy to get backwards, and each one of
them was a real design decision:

- the timeline reports **completions**, not dispatches;
- a **failed** run is told apart from a slow one by a marker, never by ``next``;
- a duration that cannot be computed is **unknown**, never zero.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.domain.graph.progress import RUN_FAILED_PREFIX, build_progress, build_timeline


def snap(nxt: tuple, at: str, values: dict | None = None):
    """A checkpoint, duck-typed the way LangGraph's StateSnapshot is read."""
    return SimpleNamespace(next=nxt, created_at=at, values=values or {})


HISTORY = [
    snap(("__start__",), "2026-09-20T10:00:00+00:00"),
    snap(("supervisor",), "2026-09-20T10:00:01+00:00"),
    snap(("requirements_extractor",), "2026-09-20T10:00:03+00:00"),
    snap(("supervisor",), "2026-09-20T10:00:12+00:00"),
    snap(("budget_searcher",), "2026-09-20T10:00:13+00:00"),
    snap((), "2026-09-20T10:00:40+00:00", {"status": "validated", "estimate": {"total_hours": 160}}),
]


def test_the_start_pseudo_node_is_not_a_step():
    # It is not something anyone ran, and it would put a phantom first row in
    # every feed.
    assert [step["node"] for step in build_timeline(HISTORY)] == [
        "supervisor",
        "requirements_extractor",
        "supervisor",
        "budget_searcher",
    ]


def test_a_node_is_closed_off_by_the_next_snapshot():
    """The whole reason this reads the history: the state has no timestamps, so
    a duration can only come from two consecutive checkpoints."""
    extractor = build_timeline(HISTORY)[1]

    assert extractor["node"] == "requirements_extractor"
    assert extractor["started_at"] == "2026-09-20T10:00:03+00:00"
    assert extractor["finished_at"] == "2026-09-20T10:00:12+00:00"
    assert extractor["seconds"] == 9.0


def test_the_last_node_is_still_in_flight_and_has_no_duration():
    running = build_timeline(HISTORY[:-1])[-1]

    assert running["node"] == "budget_searcher"
    assert running["finished_at"] is None
    # Not 0.0: a zero reads as an instantaneous node, which a dashboard averages.
    assert running["seconds"] is None


def test_an_unparseable_timestamp_is_an_unknown_duration_not_a_zero():
    steps = build_timeline([snap(("supervisor",), "no es una fecha"), snap((), "tampoco")])

    assert steps[0]["seconds"] is None


def test_a_fan_out_gives_every_branch_its_own_row():
    steps = build_timeline(
        [snap(("a", "b"), "2026-09-20T10:00:00+00:00"), snap((), "2026-09-20T10:00:05+00:00")]
    )

    assert [s["node"] for s in steps] == ["a", "b"]
    assert all(s["seconds"] == 5.0 for s in steps)


# --- the status ---------------------------------------------------------------


def test_a_finished_run_is_finished():
    report = build_progress(HISTORY)

    assert report["status"] == "finished"
    assert report["current"] is None
    assert report["last_activity_at"] == "2026-09-20T10:00:40+00:00"


def test_a_run_in_flight_names_what_is_running_now():
    report = build_progress(HISTORY[:-1])

    assert report["status"] == "running"
    assert report["current"] == "budget_searcher"


def test_a_crashed_run_is_failed_even_though_next_still_names_a_node():
    """``aupdate_state`` leaves ``next`` pointing at the node that died, so the
    shape of the checkpoint cannot tell a dead run from a working one. The
    marker in ``errors`` is the only signal, and this is what it buys."""
    history = HISTORY[:-1] + [
        snap(
            ("budget_searcher",),
            "2026-09-20T10:00:13+00:00",
            {"errors": [f"{RUN_FAILED_PREFIX}RuntimeError: provider down"]},
        )
    ]

    report = build_progress(history)

    assert report["status"] == "failed"
    assert report["failure"] == "RuntimeError: provider down"
    # And nothing is reported as running: a stuck run read as a busy one is
    # exactly the screen that polls forever.
    assert report["current"] is None


def test_the_failure_marker_is_not_repeated_among_the_run_errors():
    history = HISTORY[:-1] + [
        snap(
            ("budget_searcher",),
            "2026-09-20T10:00:13+00:00",
            {
                "errors": [
                    "search_budgets(App móvil): RuntimeError",
                    f"{RUN_FAILED_PREFIX}TimeoutError: too slow",
                ]
            },
        )
    ]

    report = build_progress(history)

    assert report["errors"] == ["search_budgets(App móvil): RuntimeError"]
    assert report["failure"] == "TimeoutError: too slow"


def test_a_paused_run_outranks_everything_else():
    report = build_progress(HISTORY[:-1], review_payload={"reason": "confidence 0.31"})

    assert report["status"] == "awaiting_human_review"
    assert report["current"] is None
    assert report["review_payload"]["reason"] == "confidence 0.31"


def test_an_empty_history_does_not_explode():
    report = build_progress([])

    assert report["status"] == "running"
    assert report["steps"] == []
    assert report["last_activity_at"] is None


def test_the_counts_come_from_the_latest_snapshot():
    history = [
        snap(("supervisor",), "2026-09-20T10:00:00+00:00"),
        snap(
            (),
            "2026-09-20T10:00:20+00:00",
            {
                "requirements": ["a", "b"],
                "components": [{"id": "c1"}],
                "budget_matches": [{"amount": 1}, {"amount": 2}],
                "routing_steps": 5,
                "estimate": {"total_hours": 160},
                "confidence": 0.81,
            },
        ),
    ]

    counts = build_progress(history)["counts"]

    assert counts == {
        "requirements": 2,
        "components": 1,
        "budget_matches": 2,
        "routing_steps": 5,
        "has_estimate": True,
        "confidence": 0.81,
    }
