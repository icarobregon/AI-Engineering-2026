#!/usr/bin/env python3
"""Calibrate ``RAG_DISTANCE_THRESHOLD`` against the real corpus.

The default of 0.6 comes from the session material, not from this corpus. A
threshold is only meaningful relative to a corpus and an embedding model, so
this script measures the actual distribution of cosine distances for real
queries and shows what each candidate threshold would let through.

Two query families, on purpose:

* **reformulated** — the ``search_text`` the Query stage produces for each
  transcript in ``examples/transcripts/``. This is what the threshold will
  really see in production.
* **raw transcript** — the same transcripts embedded whole (the Session 8
  behaviour), kept as the control that shows why the threshold cannot be tuned
  against them.

Reformulations are cached in ``examples/reformulated_queries.json`` so repeated
runs cost nothing. Delete that file (or pass ``--refresh``) to re-extract.

Usage::

    docker compose up -d
    uv run python scripts/s09_calibrate_threshold.py
    uv run python scripts/s09_calibrate_threshold.py --refresh --top-k 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies import (  # noqa: E402
    get_embedder,
    get_query_reformulator,
    get_semantic_retriever,
)
from app.generation.rag.schemas import RetrievalFilters  # noqa: E402

TRANSCRIPTS_DIR = ROOT / "examples" / "transcripts"
CACHE_PATH = ROOT / "examples" / "reformulated_queries.json"
CANDIDATE_THRESHOLDS = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75]


def load_reformulations(*, refresh: bool) -> dict[str, str]:
    """``{transcript name: search_text}``, extracting only when needed."""
    cache: dict[str, str] = {}
    if CACHE_PATH.exists() and not refresh:
        cache = json.loads(CACHE_PATH.read_text())

    reformulator = None
    for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        if path.name in cache:
            continue
        if reformulator is None:
            reformulator = get_query_reformulator()
            if reformulator is None:
                print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
                raise SystemExit(1)
        print(f"  reformulating {path.name}…")
        cache[path.name] = reformulator.reformulate(path.read_text(encoding="utf-8")).search_text

    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))
    return cache


async def distances_for(query_text: str, top_k: int) -> list[float]:
    """Every distance in the top-K, with the threshold effectively disabled."""
    retriever = get_semantic_retriever()
    result = await retriever.retrieve(
        search_text=query_text,
        top_k=top_k,
        distance_threshold=2.0,  # cosine distance never exceeds 2
        filters=RetrievalFilters(),
    )
    return [chunk.distance for chunk in result.chunks]


def summarize(label: str, distances: list[float]) -> None:
    if not distances:
        print(f"  {label:<34} (no results)")
        return
    spread = max(distances) - min(distances)
    print(
        f"  {label:<34} min={min(distances):.4f}  p50={statistics.median(distances):.4f}  "
        f"max={max(distances):.4f}  spread={spread:.4f}"
    )


def threshold_table(rows: dict[str, list[float]]) -> None:
    print("\nChunks passing each candidate threshold (top-K considered):\n")
    header = "  " + "query".ljust(34) + "".join(f"{t:>7}" for t in CANDIDATE_THRESHOLDS)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for label, distances in rows.items():
        counts = "".join(
            f"{sum(1 for d in distances if d < t):>7}" for t in CANDIDATE_THRESHOLDS
        )
        print(f"  {label.ljust(34)}{counts}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--refresh", action="store_true", help="Re-run the reformulations.")
    args = parser.parse_args()

    if get_embedder() is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        raise SystemExit(1)

    print("Reformulating transcripts (cached in examples/reformulated_queries.json)")
    reformulations = load_reformulations(refresh=args.refresh)

    print("\nDistance distribution (top-K, no threshold applied)\n")
    rows: dict[str, list[float]] = {}

    for name, search_text in sorted(reformulations.items()):
        distances = await distances_for(search_text, args.top_k)
        label = f"reformulated · {name}"
        rows[label] = distances
        summarize(label, distances)

    for path in sorted(TRANSCRIPTS_DIR.glob("*.txt")):
        distances = await distances_for(path.read_text(encoding="utf-8"), args.top_k)
        label = f"raw transcript · {path.name}"
        rows[label] = distances
        summarize(label, distances)

    threshold_table(rows)

    reformulated = [d for label, ds in rows.items() if label.startswith("reformulated") for d in ds]
    raw = [d for label, ds in rows.items() if label.startswith("raw") for d in ds]
    print("\nSummary")
    print(f"  reformulated queries : p10={_percentile(reformulated, 10):.4f}  "
          f"p50={statistics.median(reformulated):.4f}")
    print(f"  raw transcripts      : p10={_percentile(raw, 10):.4f}  "
          f"p50={statistics.median(raw):.4f}")
    print(
        "\n  A useful threshold sits above the best distances of reformulated queries\n"
        "  (so real matches survive) and below the bulk of raw-transcript distances\n"
        "  (so diluted queries soft-fail instead of returning plausible noise)."
    )


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct / 100))
    return ordered[index]


if __name__ == "__main__":
    asyncio.run(main())
