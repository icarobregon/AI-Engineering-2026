"""Compiled-SQL tests for the lexical branch (Session 10).

``ChunkStore.search_lexical`` builds the only string surgery on rendered SQL in the
codebase (``_or_tsquery`` rewrites ``plainto_tsquery``'s ``&`` into ``|``), and until
now no test executed it: the suite reported ``repository.py`` at 34%, and dropping
``.where(*_structural_filters(...))`` from the lexical branch left all tests green
while a ``sectors=["ecommerce"]`` request happily returned healthcare budgets.

There is no test database in this project and none is needed here. A capturing
session records the statement the store builds, and we assert on the SQL it compiles
to. That covers the predicates, the ordering and the limit — everything except what
PostgreSQL does with them, which the migration tests and the live harness cover.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.generation.rag.store.models import TEXT_SEARCH_CONFIG
from app.generation.rag.store.repository import ChunkStore


class CapturingSession:
    """Records the statement instead of executing it."""

    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(all=lambda: [])


async def _capture(**kwargs) -> tuple[str, dict]:
    session = CapturingSession()
    await ChunkStore().search_lexical(session, **kwargs)
    compiled = session.statement.compile(dialect=postgresql.dialect())
    return str(compiled), dict(compiled.params)


async def test_lexical_query_matches_the_tsvector_column_via_the_match_operator():
    sql, _ = await _capture(query_text="stripe subscriptions", top_k=50)
    # @@ is what the GIN index serves; anything else silently degrades to a scan.
    assert "content_tsv @@" in sql


async def test_lexical_query_uses_the_shared_text_search_configuration():
    """Building the vector with one configuration and querying with another
    silently under-matches, so both sides must use the same constant."""
    _, params = await _capture(query_text="stripe subscriptions", top_k=50)
    assert TEXT_SEARCH_CONFIG in params.values()


async def test_lexical_ranking_is_ordered_and_deterministic():
    sql, _ = await _capture(query_text="stripe", top_k=50)
    lowered = sql.lower()
    assert "ts_rank" in lowered
    assert "order by" in lowered
    # Rank descending, then id ascending: real ties exist in the corpus, and the
    # fusion built on top of this ordering has to be reproducible.
    order_by = lowered.split("order by", 1)[1]
    assert "desc" in order_by
    assert "chunks.id" in order_by
    assert "limit" in lowered


async def test_top_k_reaches_the_query_as_the_limit():
    _, params = await _capture(query_text="stripe", top_k=37)
    assert 37 in params.values()


def _where(sql: str) -> str:
    """The WHERE clause only, whitespace-normalised."""
    assert "WHERE" in sql
    return " ".join(sql.split("WHERE", 1)[1].split("ORDER BY")[0].split())


@pytest.mark.parametrize(
    "kwargs,expected_params,expected_sql",
    [
        # The JSONB keys compile to BOUND PARAMETERS, not to SQL literals, so the
        # assertion has to look in both places for these axes.
        ({"sectors": ["ecommerce"]}, ["client_sector", ["ecommerce"]], "chunks.metadata ->>"),
        ({"project_year_min": 2022}, ["year", 2022], ">="),
        ({"project_year_max": 2024}, ["year", 2024], "<="),
        ({"chunk_types": ["budget_component"]}, [["budget_component"]], "chunks.chunk_type IN"),
    ],
)
async def test_each_structural_filter_reaches_the_lexical_sql(
    kwargs, expected_params, expected_sql
):
    """The invariant the existing test only checked against a fake store.

    If the lexical branch filtered differently from the vector branch, hybrid search
    would fuse two rankings drawn from different populations — wrong in a way no test
    of either branch alone would catch. Verified: dropping
    ``.where(*_structural_filters(...))`` from ``search_lexical`` left all 343 tests
    green while a ``sectors=["ecommerce"]`` request returned healthcare budgets.
    """
    sql, params = await _capture(query_text="stripe", top_k=50, **kwargs)
    where = _where(sql)
    assert expected_sql in where
    for expected in expected_params:
        assert expected in params.values(), f"{expected!r} not among {list(params.values())}"


async def test_no_filter_means_no_predicate_beyond_the_match():
    """``None`` means "do not filter on this axis" — it must not emit a predicate."""
    sql, params = await _capture(query_text="stripe", top_k=50)
    where = _where(sql)

    assert "content_tsv @@" in where
    assert " AND " not in where, f"unexpected extra predicate: {where}"
    assert "client_sector" not in params.values()
    assert "year" not in params.values()


async def test_or_semantics_reach_the_database():
    """The trap that would silently disable the branch: AND semantics make a long
    project description match nothing, so hybrid degrades to vector-only in silence.
    """
    sql, params = await _capture(query_text="e-commerce catalog checkout admin panel", top_k=50)
    assert "plainto_tsquery" in sql
    assert "websearch_to_tsquery" not in sql  # the AND-combining builder
    assert "&" in params.values() and "|" in params.values()
