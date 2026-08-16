#!/usr/bin/env python3
"""CAG vs RAG on the same transcript, with everything else held constant.

The honest comparison the session asks for: same model, same system prompt,
same output schema, same transcript. The only variable is what goes into the
context window.

* **CAG** — the entire corpus (every chunk in the database) pasted into the
  prompt. No retrieval, no threshold, no filters. This is the architecture the
  project used through Session 5, scaled up to today's corpus.
* **RAG** — the ``top_k`` chunks the retriever selects for the reformulated
  query.

Measured: input tokens, latency, cost, and what each answer can be audited
against. Note the asymmetry the numbers will show — at 60 chunks the corpus
still fits comfortably, so CAG is not "wrong" here; the point is what its cost
curve looks like as the corpus grows, and what it cannot give you at any size.

Usage::

    docker compose up -d
    uv run python scripts/s09_cag_vs_rag.py
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_context_assembler,
    get_estimate_generator,
    get_query_reformulator,
    get_semantic_retriever,
)
from app.foundation.persistence.database import get_async_session_factory  # noqa: E402
from app.generation.rag.context_assembler import build_context_block, _ENCODING  # noqa: E402
from app.generation.rag.schemas import RetrievalFilters, RetrievedChunk  # noqa: E402
from app.generation.rag.store.models import ChunkRow  # noqa: E402

# gpt-5 pricing, USD per 1M tokens (August 2026).
PRICE_IN, PRICE_OUT = 1.25, 10.00


async def whole_corpus() -> list[RetrievedChunk]:
    """Every chunk in the database, as if it had been pasted into the prompt."""
    factory = get_async_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    ChunkRow.id,
                    ChunkRow.content,
                    ChunkRow.chunk_type,
                    ChunkRow.metadata_.label("metadata_"),
                ).order_by(ChunkRow.id)
            )
        ).all()
    return [
        RetrievedChunk(
            id=row.id,
            content=row.content,
            chunk_type=row.chunk_type,
            distance=0.0,  # no ranking exists in CAG; every source is "equally there"
            sector=(row.metadata_ or {}).get("client_sector"),
            project_year=(row.metadata_ or {}).get("year"),
            country=(row.metadata_ or {}).get("country"),
            budget_id=(row.metadata_ or {}).get("budget_id"),
            component_id=(row.metadata_ or {}).get("component_id"),
        )
        for row in rows
    ]


class _Context:
    """Minimal stand-in for AssembledContext (CAG skips the assembler)."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.block = build_context_block(chunks)
        self.dropped = 0

    @property
    def valid_source_ids(self) -> set[int]:
        return {c.id for c in self.chunks}


def report(label: str, context, outcome, elapsed: float) -> None:
    tokens = len(_ENCODING.encode(context.block))
    estimate = outcome.estimate
    cited = {c.source_id for c in estimate.sources}
    print(f"\n── {label}")
    print(f"   context: {len(context.chunks)} chunks · {tokens} tokens "
          f"(~${tokens / 1_000_000 * PRICE_IN:.4f} in)")
    print(f"   latency: {elapsed:.1f}s")
    print(f"   total_engineer_days={estimate.total_engineer_days} "
          f"confidence={estimate.confidence} components={len(estimate.cost_breakdown)}")
    print(f"   citations: {len(cited)} distinct source ids {sorted(cited)}")
    print(f"   invalid citations: {outcome.invalid_citations}")
    print(f"   assumptions: {len(estimate.assumptions)}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript", type=Path, default=ROOT / "examples" / "transcripts" / "02_ambiguous.txt"
    )
    args = parser.parse_args()

    settings = get_settings()
    reformulator = get_query_reformulator()
    generator = get_estimate_generator()
    if reformulator is None or generator is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        raise SystemExit(1)

    transcript = args.transcript.read_text(encoding="utf-8")
    print(f"Transcript: {args.transcript.name} ({len(transcript)} chars)")
    print(f"Model: {settings.RAG_GENERATION_MODEL} "
          f"(reasoning={settings.RAG_GENERATION_REASONING_EFFORT})")

    # The query stage is shared: CAG still needs to know what to estimate.
    reformulation = reformulator.reformulate(transcript)

    # --- CAG: the whole corpus in the prompt --------------------------------
    cag_context = _Context(await whole_corpus())
    started = time.perf_counter()
    cag_outcome = generator.generate(
        context=cag_context, query=reformulation.query, search_text=reformulation.search_text
    )
    report("CAG · whole corpus in context", cag_context, cag_outcome, time.perf_counter() - started)

    # --- RAG: retrieved top-K ----------------------------------------------
    retrieval = await get_semantic_retriever().retrieve(
        search_text=reformulation.search_text,
        top_k=settings.RAG_TOP_K,
        distance_threshold=settings.RAG_DISTANCE_THRESHOLD,
        filters=RetrievalFilters(),
    )
    rag_context = get_context_assembler().assemble(retrieval.chunks)
    started = time.perf_counter()
    rag_outcome = generator.generate(
        context=rag_context, query=reformulation.query, search_text=reformulation.search_text
    )
    report("RAG · retrieved top-K", rag_context, rag_outcome, time.perf_counter() - started)

    cag_tokens = len(_ENCODING.encode(cag_context.block))
    rag_tokens = len(_ENCODING.encode(rag_context.block))
    print(
        f"\nContext ratio: CAG carries {cag_tokens / max(rag_tokens, 1):.1f}× the tokens of RAG "
        f"for this request.\nAt 17 budgets that is affordable; the ratio is what scales with the "
        f"corpus, not the\nquality of the answer."
    )


if __name__ == "__main__":
    asyncio.run(main())
