"""Augmentation stage: retrieved chunks → a context block the model can use.

Three decisions live here, and all three are about making the model's job
mechanical rather than interpretive:

* **Delimiters with metadata as attributes.** Each chunk is wrapped in a
  ``<source>`` tag carrying its id, sector, year, type and distance. The id is
  what makes citation possible at all, and having the distance in the prompt
  lets the model weigh a 0.39 match differently from a 0.58 one.
* **Truncation at whole-chunk granularity, counting the wrapper.** Half a
  budget component is worse than no component: the model would cite an id whose
  numbers it never saw. And the wrapper is not free — at 10 chunks it is
  several hundred tokens that a naive count of ``chunk.content`` misses.
* **U-shaped reordering, off by default.** *Lost in the middle* (Liu et al.,
  2023) is real but its magnitude depends on K and on the model. At K=10 with
  a reasoning model there is nothing to fix; the knob exists so the decision
  can be made from measurement (``scripts/s09_lost_in_the_middle.py``) rather
  than from folklore.
"""

from __future__ import annotations

import tiktoken

from app.generation.rag.schemas import RetrievedChunk

# The generation models (gpt-5 family) use o200k_base. Note this is a different
# tokenizer from the embedding one used in ``chunking/base.py`` (cl100k_base) —
# on purpose: each budget is counted against the model that will consume it.
_ENCODING = tiktoken.get_encoding("o200k_base")

# Share of the total budget spent on retrieved context. The rest is reserved
# for the answer (15%) and prompt overhead: system message, instructions and
# the serialized structured query (5%).
CONTEXT_SHARE = 0.80
OUTPUT_SHARE = 0.15
OVERHEAD_SHARE = 0.05


def wrap_chunk(chunk: RetrievedChunk) -> str:
    """Render one chunk as a ``<source>`` block with metadata as attributes."""
    attrs = " ".join(
        [
            f'id="{chunk.id}"',
            f'sector="{chunk.sector or "unknown"}"',
            f'project_year="{chunk.project_year or "unknown"}"',
            f'chunk_type="{chunk.chunk_type}"',
            f'distance="{chunk.distance:.3f}"',
        ]
    )
    return f"<source {attrs}>\n{chunk.content.strip()}\n</source>"


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Join the wrapped chunks into the block that goes into the user prompt."""
    return "\n\n".join(wrap_chunk(chunk) for chunk in chunks)


def truncate_to_token_budget(
    chunks: list[RetrievedChunk], max_context_tokens: int
) -> list[RetrievedChunk]:
    """Keep chunks, in order, while the *wrapped* form fits the budget.

    Stops at the first chunk that does not fit instead of skipping it and
    trying the next: the list arrives sorted by relevance, so continuing would
    silently prefer a shorter, less relevant chunk over a longer, better one.
    """
    selected: list[RetrievedChunk] = []
    used = 0
    for chunk in chunks:
        size = len(_ENCODING.encode(wrap_chunk(chunk)))
        if used + size > max_context_tokens:
            break
        selected.append(chunk)
        used += size
    return selected


def reorder_u_pattern(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Most relevant at the edges, least relevant in the middle."""
    front, back = [], []
    for index, chunk in enumerate(chunks):
        (front if index % 2 == 0 else back).append(chunk)
    return front + list(reversed(back))


class AssembledContext:
    """The context block plus the chunks that actually made it in.

    The distinction matters downstream: citation validation must run against
    the chunks the model *saw*, not against everything retrieval returned. A
    chunk dropped by truncation is, for the generator, a chunk that never
    existed — and an id it must never cite.
    """

    def __init__(self, block: str, chunks: list[RetrievedChunk], dropped: int) -> None:
        self.block = block
        self.chunks = chunks
        self.dropped = dropped

    @property
    def valid_source_ids(self) -> set[int]:
        return {chunk.id for chunk in self.chunks}


class ContextAssembler:
    """Turns a retrieval result into a bounded, delimited context block."""

    def __init__(self, *, token_budget: int, reorder_u: bool = False) -> None:
        self._token_budget = token_budget
        self._reorder_u = reorder_u

    @property
    def max_context_tokens(self) -> int:
        return int(self._token_budget * CONTEXT_SHARE)

    def assemble(self, chunks: list[RetrievedChunk]) -> AssembledContext:
        selected = truncate_to_token_budget(chunks, self.max_context_tokens)
        dropped = len(chunks) - len(selected)
        # Reordering AFTER truncation: truncation must cut the least relevant
        # chunks, and after a U-reorder those are no longer at the end.
        ordered = reorder_u_pattern(selected) if self._reorder_u else selected
        return AssembledContext(build_context_block(ordered), ordered, dropped)
