#!/usr/bin/env python3
"""Seed the vector store with the sample budget corpus.

Loads ``data/budgets_sample.json`` (a list of historical budgets) and ingests
each one as its own document via ``POST /embeddings/ingest``. The ``source_path``
is ``data/budgets_sample.json#<budget_id>`` so each budget is a distinct,
idempotent document: re-running the script skips already-ingested budgets (409).

Usage::

    # inside the container (the API must be up):
    docker compose exec estimator python scripts/seed_corpus.py

    # outside the container (from the estimator/ dir, with .env present):
    uv run python scripts/seed_corpus.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

CORPUS = ROOT / "data" / "budgets_sample.json"
SOURCE_PREFIX = "data/budgets_sample.json"
DOCUMENT_TYPE = "historical_budget"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the vector store from the sample corpus.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Estimator API base URL.")
    parser.add_argument("--corpus", type=Path, default=CORPUS, help="Path to the budgets JSON.")
    args = parser.parse_args()

    budgets = json.loads(args.corpus.read_text(encoding="utf-8"))
    print(f"Seeding {len(budgets)} budgets from {args.corpus.name} → {args.base_url}\n")

    ingested = skipped = failed = 0
    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        for budget in budgets:
            source_path = f"{SOURCE_PREFIX}#{budget['budget_id']}"
            resp = client.post(
                "/embeddings/ingest",
                json={
                    "source_path": source_path,
                    "document_type": DOCUMENT_TYPE,
                    "content": budget,
                },
            )
            if resp.status_code == 200:
                body = resp.json()
                ingested += 1
                print(
                    f"  ✅ {source_path}: document_id={body['document_id']} "
                    f"chunks={body['chunks_created']} ({body['ingestion_time_ms']} ms)"
                )
            elif resp.status_code == 409:
                skipped += 1
                print(f"  ⏭️  {source_path}: already ingested, skipping")
            else:
                failed += 1
                print(f"  ❌ {source_path}: HTTP {resp.status_code} — {resp.text[:200]}")

    print(f"\nDone. ingested={ingested} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
