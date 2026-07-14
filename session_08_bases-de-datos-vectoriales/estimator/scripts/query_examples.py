#!/usr/bin/env python3
"""Exercise the semantic search endpoint with five representative queries.

Replaces the Session 7 ``compare.py`` (which measured similarity between two
ad-hoc texts) with a driver that hits ``POST /search`` over the persisted corpus.
The five queries probe the dataset from different angles: a direct known match,
a semantic reformulation, an out-of-domain query, an ambiguous one and a very
specific one. Run ``seed_corpus.py`` first so there is data to search.

Usage::

    # inside the container (API up, corpus seeded):
    docker compose exec estimator python scripts/query_examples.py

    # capture the deliverable:
    docker compose exec estimator python scripts/query_examples.py > output_examples.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

QUERIES: list[tuple[str, str]] = [
    ("Direct known component", "REST API development with JWT authentication for financial sector"),
    ("Semantic reformulation", "secure backend service with token-based access control for banking applications"),
    ("Out-of-domain", "mobile application for restaurant reservations"),
    ("Ambiguous / generic", "integration with external system"),
    ("Very specific", "migration from monolith to microservices architecture using Kubernetes"),
]

K = 5
CONTENT_PREVIEW = 120


def main() -> int:
    parser = argparse.ArgumentParser(description="Run example queries against POST /search.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Estimator API base URL.")
    parser.add_argument("-k", type=int, default=K, help="Results per query.")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        for label, query in QUERIES:
            print("=" * 100)
            print(f"[{label}] {query}")
            resp = client.post("/search", json={"query": query, "k": args.k})
            if resp.status_code != 200:
                print(f"  ❌ HTTP {resp.status_code} — {resp.text[:200]}")
                continue

            body = resp.json()
            print(f"  ({body['search_time_ms']} ms, k={body['k']})")
            for rank, hit in enumerate(body["results"], start=1):
                preview = " ".join(hit["content"].split())[:CONTENT_PREVIEW]
                print(
                    f"   {rank}. chunk_id={hit['chunk_id']:<5} "
                    f"distance={hit['distance']:.4f}  "
                    f"[{hit['chunk_type']}]  {preview}"
                )
            print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
