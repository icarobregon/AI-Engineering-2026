#!/usr/bin/env python3
"""Run the Session 13 estimation graph over a transcript and print its trace.

Three ways to run it, differing only in what is real:

* **Offline** — ``--memory --stub``: checkpoints in memory, canned budgets, no
  Postgres and no containers. Only the three LLM nodes hit the network, so this
  is the cheap way to debug the wiring::

      uv run python scripts/run_graph_s13.py --memory --stub

* **Real** — the project's Postgres for both the retrieval and the checkpoints.
  Needs the stack up and the task corpus ingested
  (``scripts/build_task_corpus.py --ingest``)::

      docker compose exec estimator python scripts/run_graph_s13.py \
          --out exercises/session-13/example_run_complex.txt

* **Traced** — the same, with ``LOGFIRE_TOKEN`` set, which exports one span per
  node inside the run's trace.

The console trace comes from ``astream(stream_mode="updates")``: one block per
node, in the order the graph actually ran them, showing what each one wrote to
the state. That is the graph's own account of the run, not a reconstruction.
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

from app.config import get_settings  # noqa: E402
from app.domain.graph.build import build_graph  # noqa: E402
from app.domain.graph.observability import configure_observability  # noqa: E402

DEFAULT_TRANSCRIPT = REPO_ROOT / "exercises" / "session-12" / "sample_transcript_complex.txt"
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
    """One node's contribution to the run, as the graph reported it."""
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


def _render_final(state: dict) -> str:
    estimate = state.get("estimate") or {}
    header = f"FINAL — {estimate.get('project', 'estimate')}  [status: {state.get('status')}]"
    lines = [header, "=" * len(header), ""]
    for component in estimate.get("components") or []:
        flag = "" if component.get("grounded") else "  [NOT GROUNDED]"
        lines.append(f"- {component.get('name')}: {component.get('estimated_hours')}h{flag}")
        lines.append(f"    {component.get('rationale')}")
    lines.append("")
    lines.append(f"TOTAL: {estimate.get('total_hours')}h")
    lines.append(f"Notes: {estimate.get('notes')}")
    if state.get("errors"):
        lines.append("")
        lines.append("Errors recorded during the run:")
        lines.extend(f"  - {e}" for e in state["errors"])
    return "\n".join(lines)


async def _run(graph, transcript: str, thread_id: str) -> tuple[list[str], dict]:
    blocks: list[str] = []
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": get_settings().GRAPH_RECURSION_LIMIT,
    }
    step = 0
    started = time.perf_counter()
    # One span around the whole run so the per-node spans nest INSIDE it. Without
    # a parent, each node opens its own root span and the run arrives as five
    # unrelated traces — which is not the "one trace with a span per node" the
    # exercise asks for. Under the HTTP endpoint the parent is the request span;
    # here it has to be opened by hand.
    with logfire.span("estimation graph run", thread_id=config["configurable"]["thread_id"]):
        async for chunk in graph.astream({"transcript": transcript}, config, stream_mode="updates"):
            for node, update in chunk.items():
                step += 1
                elapsed = (time.perf_counter() - started) * 1000
                blocks.append(_render_update(step, node, update, elapsed))
                started = time.perf_counter()
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
    # for it. Building the nodes here instead would be a second wiring site that
    # drifts from the real one — which it did, and the deliverable run paid for
    # it with a timeout the service was already configured against.
    nodes = get_graph_nodes(search_backend=_load_stub_backend() if args.stub else None)
    thread_id = args.thread_id or f"run-{args.transcript.stem}-{int(time.time())}"

    print(
        f"Running the graph on {args.transcript.name} "
        f"(checkpointer={'memory' if args.memory else 'postgres'}, "
        f"retrieval={'stub' if args.stub else 'real'}, "
        f"logfire={'exporting' if exporting else 'local'}, thread_id={thread_id})\n",
        file=sys.stderr,
    )

    if args.memory:
        from langgraph.checkpoint.memory import MemorySaver

        blocks, state = await _run(
            build_graph(nodes, checkpointer=MemorySaver()),
            args.transcript.read_text(encoding="utf-8"),
            thread_id,
        )
    else:
        from app.domain.graph.checkpointer import open_checkpointer

        async with open_checkpointer(settings.DATABASE_URL) as checkpointer:
            blocks, state = await _run(
                build_graph(nodes, checkpointer=checkpointer),
                args.transcript.read_text(encoding="utf-8"),
                thread_id,
            )

    header = (
        f"GRAPH RUN — thread_id={thread_id} "
        f"checkpointer={'memory' if args.memory else 'postgres'} "
        f"retrieval={'stub' if args.stub else 'real'}"
    )
    report = "\n\n".join(["\n".join([header, "=" * len(header)]), *blocks, _render_final(state)])
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nRun written to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
