"""Tests for the Augmentation stage (Session 9)."""

from __future__ import annotations

from app.generation.rag.context_assembler import (
    ContextAssembler,
    build_context_block,
    reorder_u_pattern,
    truncate_to_token_budget,
    wrap_chunk,
)
from app.generation.rag.schemas import RetrievedChunk


def make_chunk(chunk_id: int, *, content: str = "Component: Auth\nDescription: OAuth 2.0.") -> RetrievedChunk:
    return RetrievedChunk(
        id=chunk_id,
        content=content,
        chunk_type="budget_component",
        distance=0.1 * chunk_id,
        sector="finance",
        project_year=2024,
        country="ES",
        budget_id="BUD-2024-001",
        component_id=f"C-{chunk_id}",
        main_technology="ruby_on_rails",
    )


def test_wrap_chunk_exposes_the_id_and_metadata_as_attributes():
    wrapped = wrap_chunk(make_chunk(7))
    assert wrapped.startswith('<source id="7" sector="finance" project_year="2024"')
    assert 'chunk_type="budget_component"' in wrapped
    assert 'distance="0.700"' in wrapped
    assert wrapped.endswith("</source>")


def test_unknown_metadata_is_labelled_not_omitted():
    chunk = make_chunk(1)
    chunk.sector = None
    chunk.project_year = None
    wrapped = wrap_chunk(chunk)
    assert 'sector="unknown"' in wrapped
    assert 'project_year="unknown"' in wrapped


def test_build_context_block_separates_sources_with_a_blank_line():
    block = build_context_block([make_chunk(1), make_chunk(2)])
    assert block.count("<source ") == 2
    assert "</source>\n\n<source " in block


def test_truncation_counts_the_wrapper_not_just_the_content():
    chunk = make_chunk(1)
    content_tokens = len(chunk.content.split())
    # A budget above the bare content but below content+wrapper must drop it.
    assert truncate_to_token_budget([chunk], content_tokens + 2) == []


def test_truncation_keeps_relevance_order_and_stops_at_the_first_misfit():
    chunks = [make_chunk(1), make_chunk(2, content="x " * 400), make_chunk(3)]
    kept = truncate_to_token_budget(chunks, 60)
    # Stops at the oversized second chunk instead of skipping to the third:
    # the list is sorted by relevance and 3 is less relevant than 2.
    assert [c.id for c in kept] == [1]


def test_u_pattern_puts_the_most_relevant_at_both_ends():
    chunks = [make_chunk(i) for i in range(1, 6)]
    assert [c.id for c in reorder_u_pattern(chunks)] == [1, 3, 5, 4, 2]


def test_assembler_reserves_20_percent_of_the_budget():
    assembler = ContextAssembler(token_budget=20_000)
    assert assembler.max_context_tokens == 16_000


def test_assembler_reports_dropped_chunks_and_valid_ids():
    chunks = [make_chunk(1), make_chunk(2, content="x " * 2000)]
    assembled = ContextAssembler(token_budget=200).assemble(chunks)
    assert assembled.dropped == 1
    assert assembled.valid_source_ids == {1}
    # An id the model must never cite: it was not in the block it saw.
    assert 'id="2"' not in assembled.block


def test_reordering_is_off_by_default():
    chunks = [make_chunk(i) for i in range(1, 6)]
    default_order = ContextAssembler(token_budget=20_000).assemble(chunks)
    reordered = ContextAssembler(token_budget=20_000, reorder_u=True).assemble(chunks)
    assert [c.id for c in default_order.chunks] == [1, 2, 3, 4, 5]
    assert [c.id for c in reordered.chunks] == [1, 3, 5, 4, 2]
