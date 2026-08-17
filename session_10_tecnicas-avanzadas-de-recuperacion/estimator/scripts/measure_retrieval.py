#!/usr/bin/env python3
"""Artisanal retrieval measurement against a hand-annotated golden set.

Turns *"it seems to work better"* — which survives neither the question "by how
much?", nor a serious code review, nor the person paying the infrastructure bill —
into *"retrieval precision went from X to Y at a cost of Z milliseconds"*.

Runs the four configurations of the exercise against ``scripts/golden_set.json``
and prints a comparison table::

    A  vector  no rerank     the Session 9 baseline
    B  hybrid  no rerank
    C  vector  rerank
    D  hybrid  rerank

Usage::

    docker compose exec estimator python scripts/measure_retrieval.py

Requires the corpus ingested (``scripts/query_examples.py`` does it, idempotently).

Why this lives in ``scripts/`` and not in the application layers: an artisanal
harness is a tool for one decision, not infrastructure. It needs no endpoint, no
abstraction for future use cases and no tests of its own. Turning it prematurely
into an "evaluation module" is the classic over-engineering nobody wants to
maintain afterwards. When the system needs continuous evaluation — automated, in
CI, with history — that will be a different piece with a different design.

MEASUREMENT DECISIONS, stated so they can be argued with:

* **Latency covers retrieval only**, not query embedding. The embedding is one
  identical network call in all four configurations, so including it would add the
  same constant to every row while importing network jitter into the comparison.
  It is measured once and reported separately as context.
* **Warm measurement.** A global warm-up runs every configuration once before
  anything is recorded, so no row pays for the cross-encoder load (~20 s), cold
  connection pools or cold caches.
* **Median, not mean**, of ``RUNS_PER_QUERY`` runs. With samples this small the
  mean follows any spike of the machine.
* **precision@5 over chunks is the headline** because 5 chunks is exactly what the
  pipeline hands the generator — measuring at another k answers a question nobody
  asked.
* **recall@5** is the free complement of having annotated every relevant budget:
  it catches the failure precision cannot see — the valuable budget that appears
  nowhere at all.
* **distinct budgets in the top 5** is a diagnostic, not a score. The chunker emits
  one chunk per budget component, so one budget can legitimately occupy several of
  the five slots — and when it does, the context block carries fewer independent
  references than it appears to.

  A tempting second metric was rejected here: deduplicating the top-5 by parent
  budget and computing precision over what remains. It inverts the meaning it
  claims to measure, because the denominator shrinks with the duplication. Measured
  on this very run, config A returned ``[005, 005, 017, 008, 017]`` → distinct
  ``[005, 017, 008]`` → 0.67, while config B returned ``[005, 005, 017, 017, 005]``
  → distinct ``[005, 017]`` → 1.00. B scores higher purely for surfacing FEWER
  distinct budgets. A metric that rewards duplication is worse than no metric,
  because it looks rigorous.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.dependencies import get_embedder, get_reranker  # noqa: E402
from app.generation.rag.retrieval.pipeline import retrieve  # noqa: E402

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.json"
TOP_K = 5
RECALL_K = 50
RUNS_PER_QUERY = 5

# (label, search_mode, rerank)
CONFIGS = [
    ("A", "vector", False),
    ("B", "hybrid", False),
    ("C", "vector", True),
    ("D", "hybrid", True),
]


def precision_at_k(budget_ids: list[str], relevant: set[str], k: int) -> float:
    """Relevant items among the top k, over k.

    The denominator is ``k``, NOT ``len(top)``. Dividing by what was actually
    returned rewards returning less: a configuration that returns 2 chunks, both
    relevant, would score 1.00 against one that returns 5 with 4 relevant scoring
    0.80 — and the comparison table would then recommend retrieving fewer
    documents. Same defect, on a different axis, as the deduplicated-precision
    metric this module rejects in its docstring.

    Dormant on the current corpus (every configuration returns a full 5), but it
    activates the moment the distance threshold is tightened, a ``sectors`` filter
    is added, or a harder query enters the golden set. Dividing by ``k`` treats a
    short result set as what it is for the consumer: missing context.
    """
    hits = sum(1 for budget_id in budget_ids[:k] if budget_id in relevant)
    return hits / k


def dedupe_preserving_order(budget_ids: list[str]) -> list[str]:
    """Collapse repeated parent budgets, keeping the best-ranked occurrence."""
    seen: set[str] = set()
    unique: list[str] = []
    for budget_id in budget_ids:
        if budget_id not in seen:
            seen.add(budget_id)
            unique.append(budget_id)
    return unique


def recall_at_k(budget_ids: list[str], relevant: set[str], k: int) -> float:
    """Fraction of ALL relevant budgets that made it into the top k.

    Only meaningful because the golden set annotates every relevant budget of the
    corpus for each query — viable at company scale, and it exposes the failure
    mode precision is blind to: the good budget that never shows up.
    """
    if not relevant:
        # Returning 0.0 here would report "found nothing" for a query where there
        # was nothing to find — which is exactly what an off-corpus negative case
        # looks like, so a deliberate soft-fail would read as a retrieval
        # regression. Recall is undefined without a ground truth; fail loudly
        # instead of averaging a lie into the table.
        raise ValueError(
            "recall_at_k is undefined for a query with no relevant documents; "
            "a negative (off-corpus) case needs a soft-fail check, not recall"
        )
    found = {budget_id for budget_id in budget_ids[:k] if budget_id in relevant}
    return len(found) / len(relevant)


async def run_once(embedding: list[float], query_text: str, mode: str, rerank: bool):
    """One retrieval through the pipeline, with the exercise's fixed widths."""
    return await retrieve(
        embedding,
        query_text,
        search_mode=mode,
        rerank=rerank,
        top_k=TOP_K,
        recall_k=RECALL_K,
        rerank_top_n=TOP_K,
        chunk_types=["budget_component"],
    )


async def main() -> int:
    golden_set = json.loads(GOLDEN_SET_PATH.read_text())
    queries = golden_set["queries"]

    embedder = get_embedder()
    if embedder is None:
        print("FAILED: no embedder available (missing OPENAI_API_KEY).", file=sys.stderr)
        return 1

    print(
        f"golden set: {len(queries)} queries · k={TOP_K} · recall_k={RECALL_K} · "
        f"{RUNS_PER_QUERY} runs/query (median)"
    )
    print(f"criterion:  {golden_set['annotation_criterion']}\n")

    # Embed every query once. The embedding is identical across configurations, so
    # it is deliberately outside the timed region (see module docstring).
    embed_times_ms: list[float] = []
    embeddings: dict[str, list[float]] = {}
    for entry in queries:
        started = time.perf_counter()
        embeddings[entry["id"]] = await asyncio.to_thread(embedder.embed_one, entry["query"])
        embed_times_ms.append((time.perf_counter() - started) * 1000)

    # Warm-up: load the cross-encoder and touch every code path once, so that no
    # measured run pays a cold cost.
    await asyncio.to_thread(get_reranker().load)
    first = queries[0]
    for _, mode, rerank in CONFIGS:
        await run_once(embeddings[first["id"]], first["query"], mode, rerank)

    results: dict[str, dict] = {}
    for label, mode, rerank in CONFIGS:
        per_query = []
        for entry in queries:
            relevant = set(entry["relevant_budget_ids"])
            embedding = embeddings[entry["id"]]

            latencies_ms = []
            result = None
            for _ in range(RUNS_PER_QUERY):
                started = time.perf_counter()
                result = await run_once(embedding, entry["query"], mode, rerank)
                latencies_ms.append((time.perf_counter() - started) * 1000)

            budget_ids = [chunk.budget_id or "?" for chunk in result.chunks]
            unique_ids = dedupe_preserving_order(budget_ids)
            per_query.append(
                {
                    "id": entry["id"],
                    "precision_chunks": precision_at_k(budget_ids, relevant, TOP_K),
                    "recall": recall_at_k(budget_ids, relevant, TOP_K),
                    "distinct_budgets": len(unique_ids),
                    "latency_ms": median(latencies_ms),
                    "retrieved": budget_ids,
                    "relevant": sorted(relevant),
                }
            )
        results[label] = {
            "mode": mode,
            "rerank": rerank,
            "per_query": per_query,
            "precision_chunks": median([q["precision_chunks"] for q in per_query]),
            "recall": median([q["recall"] for q in per_query]),
            "distinct_budgets": sum(q["distinct_budgets"] for q in per_query) / len(per_query),
            "latency_ms": median([q["latency_ms"] for q in per_query]),
        }
        # Means too: with 5 queries the median can hide a single catastrophic one.
        results[label]["precision_chunks_mean"] = sum(
            q["precision_chunks"] for q in per_query
        ) / len(per_query)
        results[label]["recall_mean"] = sum(q["recall"] for q in per_query) / len(per_query)

    _print_report(results, queries, median(embed_times_ms))
    return 0


def _print_report(results: dict, queries: list[dict], embed_ms: float) -> None:
    print("## Per-query precision@5 (chunks)\n")
    header = "| Query | " + " | ".join(label for label in results) + " |"
    print(header)
    print("|" + "---|" * (len(results) + 1))
    for index, entry in enumerate(queries):
        cells = " | ".join(
            f"{results[label]['per_query'][index]['precision_chunks']:.2f}" for label in results
        )
        print(f"| {entry['id']} | {cells} |")

    print("\n## Summary\n")
    print("| Config | Search | Rerank | precision@5 | recall@5 | distinct budgets | latency (ms) |")
    print("|---|---|---|---|---|---|---|")
    for label, data in results.items():
        print(
            f"| **{label}** | {data['mode']} | {'yes' if data['rerank'] else 'no'} "
            f"| {data['precision_chunks_mean']:.2f} | {data['recall_mean']:.2f} "
            f"| {data['distinct_budgets']:.1f} / 5 | {data['latency_ms']:.0f} |"
        )

    baseline = results["A"]
    print(
        f"\nQuery embedding, excluded from the latency column because it is the same "
        f"constant in all four rows: {embed_ms:.0f} ms (median)."
    )
    print("\n## Deltas against A (the Session 9 baseline)\n")
    for label, data in results.items():
        if label == "A":
            continue
        d_precision = data["precision_chunks_mean"] - baseline["precision_chunks_mean"]
        d_latency = data["latency_ms"] - baseline["latency_ms"]
        print(f"  {label}: precision {d_precision:+.2f}  ·  latency {d_latency:+.0f} ms")

    print("\n## What each config actually retrieved (for auditing the annotation)\n")
    for index, entry in enumerate(queries):
        print(f"  {entry['id']}  relevant={results['A']['per_query'][index]['relevant']}")
        for label, data in results.items():
            print(f"      {label}: {data['per_query'][index]['retrieved']}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
