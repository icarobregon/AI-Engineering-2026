#!/usr/bin/env python3
"""Run the Session 12 estimation agent over a transcript and print its trace.

Two ways to run it, and the difference is only where the budgets come from:

* **Real retrieval** — the agent's ``search_budgets`` goes through the S9-S11
  pipeline (hybrid + reranking) filtered to ``chunk_type='historical_task'``, so
  the stack must be up and the task corpus ingested::

      docker compose exec estimator python scripts/build_task_corpus.py --ingest
      docker compose exec estimator python scripts/run_agent_s12.py \
          exercises/session-12/sample_transcript_complex.txt --model gpt-5 --effort medium \
          --out exercises/session-12/trace_complex.txt

* **Stub** (``--stub``) — canned budgets from the kit, no database, no containers.
  For debugging the LOOP cheaply. The LLM calls are still real::

      uv run python scripts/run_agent_s12.py \
          exercises/session-12/sample_transcript_simple.txt --model gpt-5-mini --stub

Cost note: the loop is one API round-trip per turn plus one for the final typed
answer. Debug with ``gpt-5-mini`` and the simple transcript; switch to ``gpt-5``
with ``--effort medium`` only for the run you intend to keep.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import get_settings  # noqa: E402
from app.generation.agentic.agent_loop import (  # noqa: E402
    AgentRunError,
    run_estimation_agent,
)

STUB_PATH = REPO_ROOT / "exercises" / "session-12" / "reference_retrieval.py"


def _load_stub_backend():
    """Load the kit's standalone stub and adapt it to the backend signature.

    The stub deliberately has no dependency on the app package, so it is loaded by
    path rather than imported, and its ``filters`` dict is rebuilt here from the
    keyword arguments the tool passes.
    """
    spec = importlib.util.spec_from_file_location("reference_retrieval", STUB_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load the retrieval stub at {STUB_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def search(query, *, sectors=None, year_min=None, year_max=None, **_ignored):
        return module.search_budgets_stub(query, {"sectors": sectors} if sectors else None)

    return search


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("transcript", type=Path, help="Path to the meeting transcript.")
    parser.add_argument("--model", default=None, help="Overrides AGENT_MODEL.")
    parser.add_argument(
        "--effort",
        choices=["minimal", "low", "medium", "high"],
        default=None,
        help="Overrides AGENT_REASONING_EFFORT.",
    )
    parser.add_argument(
        "--max-iterations", type=int, default=None, help="Overrides AGENT_MAX_ITERATIONS."
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use the kit's canned budgets instead of the real retrieval pipeline.",
    )
    parser.add_argument("--out", type=Path, default=None, help="Also write the trace here.")
    args = parser.parse_args()

    if not args.transcript.is_file():
        print(f"Transcript not found: {args.transcript}", file=sys.stderr)
        return 2

    settings = get_settings()
    from app.dependencies import get_async_openai_client, get_budget_search_backend

    client = get_async_openai_client()
    if client is None:
        print("OPENAI_API_KEY is not configured — the agent needs it.", file=sys.stderr)
        return 2

    backend = _load_stub_backend() if args.stub else get_budget_search_backend()
    model = args.model or settings.AGENT_MODEL
    effort = args.effort or settings.AGENT_REASONING_EFFORT
    max_iterations = args.max_iterations or settings.AGENT_MAX_ITERATIONS

    print(
        f"Running the agent on {args.transcript.name} "
        f"(model={model}, effort={effort}, retrieval={'stub' if args.stub else 'real'})...\n",
        file=sys.stderr,
    )

    try:
        estimate, trace = await run_estimation_agent(
            args.transcript.read_text(encoding="utf-8"),
            client=client,
            backend=backend,
            model=model,
            reasoning_effort=effort,
            max_iterations=max_iterations,
        )
    except AgentRunError as exc:
        # The run failed to close, but everything before it was paid for and is
        # the point of the exercise. Print the trace, then fail loudly.
        print(exc.trace.render())
        if args.out:
            args.out.write_text(exc.trace.render() + "\n", encoding="utf-8")
        print(f"\nNo estimate produced: {exc}", file=sys.stderr)
        return 1

    report = "\n\n".join([trace.render(), _render_estimate(estimate)])
    print(report)
    if args.out:
        args.out.write_text(report + "\n", encoding="utf-8")
        print(f"\nTrace written to {args.out}", file=sys.stderr)
    return 0


def _render_estimate(estimate) -> str:
    header = f"FINAL ESTIMATE — {estimate.project}"
    lines = [header, "=" * len(header), ""]
    for component in estimate.components:
        flag = "" if component.grounded else "  [NOT GROUNDED]"
        lines.append(f"- {component.name}: {component.estimated_hours}h{flag}")
        lines.append(f"    {component.rationale}")
    lines.append("")
    lines.append(f"TOTAL: {estimate.total_hours}h")
    lines.append(f"Notes: {estimate.notes}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
