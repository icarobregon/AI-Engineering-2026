#!/usr/bin/env python3
"""Does chunk position change the estimate? (Liu et al., 2023)

Same transcript, same retrieved chunks, same model. The only variable is the
order they appear in the context block:

* **relevance** — most relevant first, which is what the assembler does today.
* **critical-in-middle** — the closest chunk buried at the centre, the position
  the paper identifies as the weakest for recall.
* **u-pattern** — the mitigation the assembler can switch on
  (``RAG_CONTEXT_REORDER_U``).

The measurable question is not "is the answer different" (a reasoning model
varies run to run anyway) but "does the model still *use* the critical chunk" —
whether its id survives in the citations, and whether the total moves.

Because a single run of each order proves little against model variance, the
number of repetitions is a flag. Each repetition is a full generation call.

Usage::

    docker compose up -d
    uv run python scripts/s09_lost_in_the_middle.py --top-k 5
    uv run python scripts/s09_lost_in_the_middle.py --repeats 3
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_estimate_generator,
    get_query_reformulator,
    get_semantic_retriever,
)
from app.generation.rag.context_assembler import (  # noqa: E402
    build_context_block,
    reorder_u_pattern,
)
from app.generation.rag.schemas import RetrievalFilters, RetrievedChunk  # noqa: E402


class _Context:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.block = build_context_block(chunks)
        self.dropped = 0

    @property
    def valid_source_ids(self) -> set[int]:
        return {c.id for c in self.chunks}


def critical_in_middle(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Move the single most relevant chunk to the centre of the list."""
    rest = chunks[1:]
    middle = len(chunks) // 2
    return rest[:middle] + [chunks[0]] + rest[middle:]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript", type=Path, default=ROOT / "examples" / "transcripts" / "02_ambiguous.txt"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()

    settings = get_settings()
    reformulator = get_query_reformulator()
    generator = get_estimate_generator()
    if reformulator is None or generator is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        raise SystemExit(1)

    transcript = args.transcript.read_text(encoding="utf-8")
    reformulation = reformulator.reformulate(transcript)
    retrieval = await get_semantic_retriever().retrieve(
        search_text=reformulation.search_text,
        top_k=args.top_k,
        distance_threshold=settings.RAG_DISTANCE_THRESHOLD,
        filters=RetrievalFilters(),
    )
    chunks = retrieval.chunks
    if len(chunks) < 3:
        print(f"Only {len(chunks)} chunks retrieved — not enough to compare orders.")
        raise SystemExit(1)

    critical = chunks[0]
    print(f"Transcript: {args.transcript.name}")
    print(f"Retrieved {len(chunks)} chunks; critical chunk = id {critical.id} "
          f"({critical.budget_id}::{critical.component_id}, distance {critical.distance:.4f})")

    orders = {
        "relevance (default)": chunks,
        "critical-in-middle": critical_in_middle(chunks),
        "u-pattern": reorder_u_pattern(chunks),
    }

    for label, ordered in orders.items():
        positions = [c.id for c in ordered]
        print(f"\n── {label}: {positions} (critical at index {positions.index(critical.id)})")
        for run in range(args.repeats):
            outcome = generator.generate(
                context=_Context(ordered),
                query=reformulation.query,
                search_text=reformulation.search_text,
            )
            estimate = outcome.estimate
            cited = {c.source_id for c in estimate.sources}
            for component in estimate.cost_breakdown:
                cited.update(component.sources)
            print(
                f"   run {run + 1}: total={estimate.total_engineer_days} "
                f"confidence={estimate.confidence} "
                f"critical_cited={'YES' if critical.id in cited else 'NO '} "
                f"cited={sorted(cited)}"
            )


if __name__ == "__main__":
    asyncio.run(main())
