#!/usr/bin/env python3
"""Trace of a raw transcript through the system as it stands after Session 8.

Backs section 2 of ``arquitectura-actual.md`` (Session 9 pre-work). Runs the
only path that exists today — embed the whole transcript, rank chunks by cosine
distance — and prints everything the write-up needs: vector stats, the raw
``POST /search`` response, and the distance spread.

To make the "length dilutes the signal" claim measurable rather than
rhetorical, it repeats the search with a short hand-written query describing
the same project. Same corpus, same endpoint, same k: the only variable is the
shape of the query text.

Usage::

    # stack up first: docker compose up -d
    uv run python scripts/s09_trace_prework.py
    uv run python scripts/s09_trace_prework.py --transcript examples/transcripts/03_hard.txt --k 10

The base URL is taken from ``ESTIMATOR_BASE_URL`` if set; otherwise the script
probes ``http://localhost:8000`` and ``http://estimator:8000`` via ``GET /health``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dependencies import get_embedder  # noqa: E402

DEFAULT_TRANSCRIPT = ROOT / "examples" / "transcripts" / "02_ambiguous.txt"
CANDIDATE_BASE_URLS = ("http://localhost:8000", "http://estimator:8000")

# Hand-written contrast query: what a human would type after reading the
# transcript. Not a reformulator — just the control for the length experiment.
SHORT_QUERY = (
    "multi-vendor marketplace for home goods with split payments between sellers "
    "and inventory synchronization between physical stores and the web shop"
)


def resolve_base_url() -> str:
    if env_url := os.environ.get("ESTIMATOR_BASE_URL"):
        return env_url.rstrip("/")
    for candidate in CANDIDATE_BASE_URLS:
        try:
            if httpx.get(f"{candidate}/health", timeout=3.0).status_code == 200:
                return candidate
        except httpx.HTTPError:
            continue
    print(
        "ERROR: no estimator API reachable. Start the stack (docker compose up -d) "
        "or set ESTIMATOR_BASE_URL.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def search(base_url: str, query: str, k: int) -> dict:
    response = httpx.post(f"{base_url}/search", json={"query": query, "k": k}, timeout=120.0)
    response.raise_for_status()
    return response.json()


def print_vector_stats(text: str) -> None:
    embedder = get_embedder()
    if embedder is None:
        print("ERROR: no OPENAI_API_KEY configured.", file=sys.stderr)
        raise SystemExit(1)

    vector = embedder.embed_one(text)
    norm = math.sqrt(sum(component * component for component in vector))
    print(f"  dimensions      : {len(vector)}")
    print(f"  first component : {vector[0]:+.6f}")
    print(f"  last component  : {vector[-1]:+.6f}")
    print(f"  L2 norm         : {norm:.6f}")


def print_hits(payload: dict) -> None:
    distances = [hit["distance"] for hit in payload["results"]]
    print(f"  search_time_ms  : {payload['search_time_ms']}")
    print(f"  results         : {len(payload['results'])}")
    for hit in payload["results"]:
        meta = hit["metadata"]
        print(
            f"    dist={hit['distance']:.4f}  chunk={hit['chunk_id']:<4}"
            f" {meta['budget_id']}::{meta['component_id']:<10}"
            f" sector={meta['client_sector']:<11} year={meta['year']}"
            f" tech={meta['main_technology']}"
        )
    if distances:
        spread = max(distances) - min(distances)
        print(f"  min={min(distances):.4f}  max={max(distances):.4f}  spread={spread:.4f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="Dump the raw /search payload too.")
    args = parser.parse_args()

    transcript = args.transcript.read_text(encoding="utf-8")
    base_url = resolve_base_url()

    print(f"Transcript      : {args.transcript.relative_to(ROOT)}")
    print(f"  characters    : {len(transcript)}")
    print(f"  lines         : {len(transcript.splitlines())}")
    print(f"API             : {base_url}\n")

    print("STEP 1 — embedding of the FULL transcript")
    print_vector_stats(transcript)

    print(f"\nSTEP 2 — POST /search with the raw transcript (k={args.k})")
    raw_payload = search(base_url, transcript, args.k)
    print_hits(raw_payload)

    print(f"\nSTEP 3 — control: POST /search with a short hand-written query (k={args.k})")
    print(f'  query: "{SHORT_QUERY}"')
    short_payload = search(base_url, SHORT_QUERY, args.k)
    print_hits(short_payload)

    if args.json:
        print("\nRAW PAYLOAD (raw transcript):")
        print(json.dumps(raw_payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
