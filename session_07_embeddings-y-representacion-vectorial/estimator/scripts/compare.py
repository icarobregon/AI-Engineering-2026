#!/usr/bin/env python3
"""Cosine-similarity sanity check between two texts.

Embeds both texts with the same ``OpenAIEmbedder`` the pipeline uses and prints
their cosine similarity, computed by hand (no numpy). A quick end-to-end check
that the pipeline discriminates near vs far content semantically.

Usage::

    uv run python scripts/compare.py --text-a "..." --text-b "..."
    # or, inside docker (scripts/ is not bind-mounted -> rebuild first):
    docker compose exec estimator python scripts/compare.py --text-a "..." --text-b "..."
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Make ``app`` importable when this script runs directly from ``scripts/``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.embedding_pipeline.embedder import OpenAIEmbedder  # noqa: E402


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Dot product divided by the product of norms — pure stdlib."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cosine similarity between two texts.")
    parser.add_argument("--text-a", required=True, help="First text.")
    parser.add_argument("--text-b", required=True, help="Second text.")
    args = parser.parse_args()

    embedder = OpenAIEmbedder()
    vec_a = embedder.embed_one(args.text_a)
    vec_b = embedder.embed_one(args.text_b)
    similarity = cosine_similarity(vec_a, vec_b)

    print(f"Text A: {args.text_a}")
    print(f"Text B: {args.text_b}")
    print(f"Cosine similarity: {similarity:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
