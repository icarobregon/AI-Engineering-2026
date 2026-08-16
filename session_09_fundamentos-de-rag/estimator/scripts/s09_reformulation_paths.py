#!/usr/bin/env python3
"""Compare the three ways of turning a transcript into something to embed.

1. **raw** — embed the transcript as it is (the Session 8 behaviour).
2. **structured** — the project's choice: extract an ``EstimationQuery`` and
   compose a search text from its fields.
3. **HyDE** — ask the model to *write the document we wish existed* (a
   plausible budget component for this project) and embed that instead. The
   premise of HyDE (Gao et al., 2022) is that a hypothetical answer lives
   closer to real answers in embedding space than a question does.

Metrics, per the session brief: how many retrieved chunks belong to the
expected sector, and how many come from the budget a human would call the
analogous one. Plus the distance distribution, because a method that retrieves
the right chunks with barely-separated scores is fragile.

Usage::

    docker compose up -d
    uv run python scripts/s09_reformulation_paths.py
    uv run python scripts/s09_reformulation_paths.py \
        --transcript examples/transcripts/01_clear.txt \
        --expected-sector healthcare --expected-budget BUD-2024-009
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies import (  # noqa: E402
    get_query_reformulator,
    get_responses_client,
    get_semantic_retriever,
)
from app.generation.rag.schemas import RetrievalFilters  # noqa: E402

HYDE_SYSTEM_PROMPT = """You write a plausible historical budget component for a \
software project, in the exact style of a consultancy's past-project database.

Given a meeting transcript, write ONE component entry for the project the client \
is asking for, in English, with this shape and nothing else:

Component: <short name>
Description: <2-3 sentences of technical scope>
Tech stack: <comma-separated technologies>
Complexity: <low|medium|high>
Estimated hours: <integer>

Invent the numbers if you must — this text is never shown to anyone, it is only \
embedded to search for similar real components."""


async def retrieve(search_text: str, top_k: int):
    retriever = get_semantic_retriever()
    result = await retriever.retrieve(
        search_text=search_text,
        top_k=top_k,
        distance_threshold=2.0,
        filters=RetrievalFilters(),
    )
    return result.chunks


def report(label: str, search_text: str, chunks, *, sector: str, budget: str) -> None:
    in_sector = sum(1 for c in chunks if c.sector == sector)
    from_budget = sum(1 for c in chunks if c.budget_id == budget)
    distances = [c.distance for c in chunks]

    print(f"\n── {label} ({len(search_text)} chars embedded)")
    print(f"   {search_text[:160].replace(chr(10), ' ')}…")
    print(
        f"   sector={sector}: {in_sector}/{len(chunks)}   "
        f"{budget}: {from_budget}/{len(chunks)}   "
        f"best={min(distances):.4f}  worst={max(distances):.4f}  "
        f"spread={max(distances) - min(distances):.4f}"
    )
    for chunk in chunks[:5]:
        mark = "✓" if chunk.budget_id == budget else " "
        print(
            f"     {mark} {chunk.distance:.4f}  {chunk.budget_id}::{chunk.component_id:<12}"
            f" {chunk.sector}/{chunk.country}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--transcript", type=Path, default=ROOT / "examples" / "transcripts" / "02_ambiguous.txt"
    )
    parser.add_argument("--expected-sector", default="ecommerce")
    parser.add_argument("--expected-budget", default="BUD-2024-006")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    reformulator = get_query_reformulator()
    responses = get_responses_client()
    if reformulator is None or responses is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        raise SystemExit(1)

    transcript = args.transcript.read_text(encoding="utf-8")
    print(f"Transcript: {args.transcript.name} ({len(transcript)} chars)")
    print(f"Expecting sector={args.expected_sector}, analogous budget={args.expected_budget}")

    # 1 — raw
    report(
        "1· RAW TRANSCRIPT",
        transcript,
        await retrieve(transcript, args.top_k),
        sector=args.expected_sector,
        budget=args.expected_budget,
    )

    # 2 — structured extraction
    structured = reformulator.reformulate(transcript)
    report(
        "2· STRUCTURED EXTRACTION",
        structured.search_text,
        await retrieve(structured.search_text, args.top_k),
        sector=args.expected_sector,
        budget=args.expected_budget,
    )

    # 3 — HyDE
    hypothetical = responses.complete_text(
        model="gpt-5-mini",
        system_prompt=HYDE_SYSTEM_PROMPT,
        user_content=transcript,
    )
    report(
        "3· HyDE (hypothetical document)",
        hypothetical,
        await retrieve(hypothetical, args.top_k),
        sector=args.expected_sector,
        budget=args.expected_budget,
    )


if __name__ == "__main__":
    asyncio.run(main())
