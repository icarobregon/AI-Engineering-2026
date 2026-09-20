#!/usr/bin/env python3
"""Run the Session 14 multi-agent system over a transcript and print its trace.

Three ways to run it, differing only in what is real:

* **Offline** — ``--memory --stub``: checkpoints in memory, canned budgets, no
  Postgres and no containers. Only the LLM agents hit the network, so this is
  the cheap way to debug the routing::

      uv run python scripts/run_graph_s14.py --memory --stub

* **Real** — the project's Postgres for both the retrieval and the checkpoints.
  Runs on the HOST against the running stack, because ``exercises/`` is not in
  the image (the runtime carries only ``app/`` plus the bind-mounted
  ``data``/``scripts``/``tests``). Needs the stack up and the task corpus
  ingested (``docker compose exec estimator python scripts/build_task_corpus.py
  --ingest``)::

      # (Redis no publica el 6379 desde la S15; ver README, vía de ejecución local)
      REDIS_URL=redis://localhost:6379 uv run python scripts/run_graph_s14.py \\
          exercises/session-14/sample_transcript_edge_case.txt \\
          --out exercises/session-14/example_run_edge_case.txt

* **Traced** — the same, with ``LOGFIRE_TOKEN`` set, which exports one span per
  agent and per routing decision inside the run's trace.

**Why this script drives the resume itself.** The acceptance criterion is a
complete trace of a run that pauses and resumes. Over HTTP those are two
requests, and OpenTelemetry cannot retro-join two traces: the resume leg arrives
as its own root span. Driving both legs inside one parent span here produces the
single trace the deliverable asks for. ``--decision`` says what the simulated
reviewer answers; the real reviewer's path is
``POST /v1/estimate/graph/{id}/resume``, which the endpoint tests cover.

The console trace comes from ``astream(stream_mode="updates")``: one block per
agent, in the order the supervisor actually chose them. That is the system's own
account of the run, not a reconstruction.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import logfire  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.domain.graph.build import build_graph  # noqa: E402
from app.domain.graph.observability import configure_observability  # noqa: E402
from app.domain.security.grants import verify_tool_grants  # noqa: E402

DEFAULT_TRANSCRIPT = REPO_ROOT / "exercises" / "session-14" / "sample_transcript_edge_case.txt"
STUB_PATH = REPO_ROOT / "exercises" / "session-12" / "reference_retrieval.py"


def _load_stub_backend():
    """Load the kit's standalone retrieval stub and adapt it to the backend."""
    spec = importlib.util.spec_from_file_location("reference_retrieval", STUB_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load the retrieval stub at {STUB_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def search(query, *, sectors=None, **_ignored):
        return module.search_budgets_stub(query, {"sectors": sectors} if sectors else None)

    return search


def _render_update(step: int, node: str, update: dict, elapsed_ms: float) -> str:
    """One agent's contribution to the run, as the graph reported it."""
    lines = [f"STEP {step} — {node}  ({elapsed_ms:.0f} ms)"]
    for key, value in (update or {}).items():
        if key == "estimate" and isinstance(value, dict):
            lines.append(
                f"  {key}: {value.get('total_hours')}h across "
                f"{len(value.get('components') or [])} components"
            )
        elif isinstance(value, list):
            lines.append(f"  {key}: {len(value)} item(s)")
            for item in value[:6]:
                lines.append(f"      - {json.dumps(item, ensure_ascii=False)[:150]}")
            if len(value) > 6:
                lines.append(f"      … {len(value) - 6} more")
        else:
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def _render_pause(payload: dict) -> str:
    """What the reviewer would see. The payload is an interface, not a log line."""
    band = payload.get("historical_band") or {}
    lines = [
        "",
        "PAUSED FOR HUMAN REVIEW",
        "=" * 22,
        f"reason: {payload.get('reason')}",
        f"confidence: {payload.get('confidence')}",
    ]
    if band:
        lines.append(
            f"comparable work has cost: {band.get('low')}-{band.get('high')}h "
            f"({band.get('covered_components')}/{band.get('total_components')} components "
            f"have a precedent)"
        )
    lines.extend(f"  trigger: {t}" for t in payload.get("triggers") or [])
    lines.extend(f"  concern: {c}" for c in payload.get("concerns") or [])
    return "\n".join(lines)


def _render_routing(state: dict) -> str:
    """The shape the run actually took. In Session 13 this was in the code."""
    header = f"ROUTING TRAIL — {state.get('routing_steps', 0)} decision(s)"
    lines = [header, "=" * len(header)]
    for index, entry in enumerate(state.get("routing_trail") or [], start=1):
        lines.append(f"  {index}. {entry.get('next_agent')} — {entry.get('reason')}")
    return "\n".join(lines)


def _render_final(state: dict) -> str:
    estimate = state.get("estimate") or {}
    header = f"FINAL — {estimate.get('project', 'estimate')}  [status: {state.get('status')}]"
    lines = [header, "=" * len(header), ""]
    for component in estimate.get("components") or []:
        flag = "" if component.get("grounded") else "  [NO PRECEDENT]"
        lines.append(f"- {component.get('name')}: {component.get('estimated_hours')}h{flag}")
        lines.append(f"    {component.get('rationale')}")
    lines.append("")
    lines.append(f"TOTAL: {estimate.get('total_hours')}h")
    if estimate.get("original_total_hours") is not None:
        lines.append(
            f"  (the system said {estimate['original_total_hours']}h; a human adjusted it)"
        )
    lines.append(f"Confidence: {state.get('confidence')}")
    lines.append(f"Notes: {estimate.get('notes')}")
    if state.get("human_decision"):
        lines.append(f"Human decision: {json.dumps(state['human_decision'], ensure_ascii=False)}")
    if state.get("errors"):
        lines.append("")
        lines.append("Errors recorded during the run:")
        lines.extend(f"  - {e}" for e in state["errors"])
    return "\n".join(lines)


async def _stream(graph, payload, config, blocks: list[str], steps: list[int]) -> dict | None:
    """One leg of the run. Returns the interrupt payload if it paused.

    ``steps`` is a one-element list so the counter survives across the two legs:
    the resume continues the same run and its steps carry on numbering from
    where the pause left off, rather than restarting at one.
    """
    pause: dict | None = None
    started = time.perf_counter()
    async for chunk in graph.astream(payload, config, stream_mode="updates"):
        for node, update in chunk.items():
            if node == "__interrupt__":
                # ainvoke returns this as a list, astream yields a tuple.
                pause = list(update)[0].value
                continue
            steps[0] += 1
            blocks.append(
                _render_update(steps[0], node, update, (time.perf_counter() - started) * 1000)
            )
            started = time.perf_counter()
    return pause


async def _run(graph, transcript: str, thread_id: str, decision: dict) -> tuple[list[str], dict]:
    blocks: list[str] = []
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": get_settings().GRAPH_RECURSION_LIMIT,
    }
    # One span around BOTH legs so every agent span nests inside it. Without a
    # parent each one opens its own root span and the run arrives as a handful of
    # unrelated traces — and the resume leg, driven separately, would be a second
    # trace no query can join back to the first.
    steps = [0]
    with logfire.span("estimation graph run", thread_id=thread_id, estimation_id=thread_id):
        pause = await _stream(
            graph, {"transcript": transcript, "estimation_id": thread_id}, config, blocks, steps
        )
        if pause is not None:
            blocks.append(_render_pause(pause))
            blocks.append(
                f"\nRESUMING with the reviewer's decision: "
                f"{json.dumps(decision, ensure_ascii=False)}"
            )
            await _stream(graph, Command(resume=decision), config, blocks, steps)

    snapshot = await graph.aget_state(config)
    return blocks, snapshot.values


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "transcript",
        nargs="?",
        type=Path,
        default=DEFAULT_TRANSCRIPT,
        help="Path to the meeting transcript.",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Checkpoint in memory instead of the project's Postgres.",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use the kit's canned budgets instead of the real retrieval pipeline.",
    )
    parser.add_argument(
        "--decision",
        choices=["approve", "adjust", "reject"],
        default="approve",
        help="What the simulated reviewer answers if the run pauses.",
    )
    parser.add_argument(
        "--adjusted-hours",
        type=float,
        default=None,
        help="The total the reviewer decides on, with --decision adjust.",
    )
    parser.add_argument("--thread-id", default=None, help="Overrides the generated thread_id.")
    parser.add_argument("--out", type=Path, default=None, help="Also write the run here.")
    args = parser.parse_args()

    if not args.transcript.is_file():
        print(f"Transcript not found: {args.transcript}", file=sys.stderr)
        return 2

    settings = get_settings()
    exporting = configure_observability()

    from app.dependencies import get_graph_nodes

    # The same wiring the service uses, with retrieval swapped when --stub asks
    # for it. Building the agents here instead would be a second wiring site that
    # drifts from the real one — which it did, and the deliverable run paid for
    # it with a timeout the service was already configured against.
    agents = get_graph_nodes(search_backend=_load_stub_backend() if args.stub else None)
    verify_tool_grants(agents)
    thread_id = args.thread_id or f"run-{args.transcript.stem}-{int(time.time())}"
    decision = {
        "action": args.decision,
        "adjusted_hours": args.adjusted_hours,
        "comment": "simulated review from scripts/run_graph_s14.py",
        "reviewer_id": "script",
    }

    print(
        f"Running the multi-agent system on {args.transcript.name} "
        f"(checkpointer={'memory' if args.memory else 'postgres'}, "
        f"retrieval={'stub' if args.stub else 'real'}, "
        f"logfire={'exporting' if exporting else 'local'}, thread_id={thread_id})\n",
        file=sys.stderr,
    )

    transcript = args.transcript.read_text(encoding="utf-8")
    if args.memory:
        from langgraph.checkpoint.memory import MemorySaver

        blocks, state = await _run(
            build_graph(agents, checkpointer=MemorySaver()), transcript, thread_id, decision
        )
    else:
        from app.domain.graph.checkpointer import open_checkpointer

        async with open_checkpointer(settings.DATABASE_URL) as checkpointer:
            blocks, state = await _run(
                build_graph(agents, checkpointer=checkpointer), transcript, thread_id, decision
            )

    header = (
        f"MULTI-AGENT RUN — thread_id={thread_id} "
        f"checkpointer={'memory' if args.memory else 'postgres'} "
        f"retrieval={'stub' if args.stub else 'real'}"
    )
    report = "\n\n".join(
        [
            "\n".join([header, "=" * len(header)]),
            *blocks,
            _render_routing(state),
            _render_final(state),
        ]
    )
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nRun written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
