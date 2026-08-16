"""Tests for the Query stage (Session 9).

No OpenAI: ``ResponsesClient`` is doubled. What is worth asserting here is the
policy, not the plumbing — what gets embedded, when the fallback fires, and
which filters we are willing to derive automatically.
"""

from __future__ import annotations

import pytest

from app.foundation.llm.responses import StructuredOutputError
from app.generation.rag.query_reformulator import (
    QueryReformulationError,
    QueryReformulator,
    compose_search_text,
    derive_filters,
)
from app.generation.rag.schemas import EstimationQuery


class FakeResponsesClient:
    """Scripted double: either returns a parsed object or raises."""

    def __init__(self, *, parsed=None, parse_error: Exception | None = None, text: str = "") -> None:
        self.parsed = parsed
        self.parse_error = parse_error
        self.text = text
        self.parse_calls: list[dict] = []
        self.text_calls: list[dict] = []

    def parse(self, **kwargs):
        self.parse_calls.append(kwargs)
        if self.parse_error is not None:
            raise self.parse_error
        return self.parsed

    def complete_text(self, **kwargs):
        self.text_calls.append(kwargs)
        if not self.text:
            raise RuntimeError("rewriting unavailable")
        return self.text


def make_query(**overrides) -> EstimationQuery:
    base = {
        "function": "multi-vendor marketplace with vendor payouts",
        "technologies": ["Stripe"],
        "sector": "ecommerce",
        "scale": "medium",
        "country": "Spain",
        "regulations": [],
        "constraints": ["stock synchronization with physical stores"],
    }
    return EstimationQuery(**{**base, **overrides})


def test_reformulate_returns_structured_query_and_composed_text():
    client = FakeResponsesClient(parsed=make_query())
    result = QueryReformulator(client, "gpt-5-mini").reformulate("… transcripción …")

    assert result.used_fallback is False
    assert result.query is not None
    assert result.query.function == "multi-vendor marketplace with vendor payouts"
    # What gets embedded is the composed text, never the raw transcript.
    assert result.search_text.startswith("multi-vendor marketplace with vendor payouts")
    assert "ecommerce" in result.search_text
    assert client.parse_calls[0]["schema"] is EstimationQuery


def test_compose_search_text_skips_empty_optional_fields():
    minimal = EstimationQuery(function="appointment booking portal")
    assert compose_search_text(minimal) == "appointment booking portal."

    full = make_query(regulations=["GDPR"])
    text = compose_search_text(full)
    assert "with Stripe" in text
    assert "for the ecommerce sector" in text
    assert "in Spain" in text
    assert "compliant with GDPR" in text
    assert text.endswith(".")


def test_structured_failure_falls_back_to_plain_rewriting():
    client = FakeResponsesClient(
        parse_error=StructuredOutputError("refusal"),
        text="Multi-vendor marketplace for home goods with split payments.",
    )
    result = QueryReformulator(client, "gpt-5-mini").reformulate("… transcripción …")

    assert result.used_fallback is True
    assert result.query is None
    assert result.search_text.startswith("Multi-vendor marketplace")
    assert len(client.text_calls) == 1


def test_fallback_failure_raises_a_single_error_type():
    client = FakeResponsesClient(parse_error=StructuredOutputError("refusal"), text="")
    with pytest.raises(QueryReformulationError):
        QueryReformulator(client, "gpt-5-mini").reformulate("… transcripción …")


def test_derive_filters_only_trusts_sectors_present_in_the_corpus():
    assert derive_filters(make_query(sector="ecommerce")).sectors == ["ecommerce"]
    # A sector the corpus does not know would empty the result set: not a filter.
    assert derive_filters(make_query(sector="home goods retail")).sectors is None
    assert derive_filters(make_query(sector=None)).is_empty()
    # Fallback path: no structured query at all means no structural filters.
    assert derive_filters(None).is_empty()


def test_derive_filters_never_derives_country_or_year():
    filters = derive_filters(make_query(country="Spain"))
    assert filters.countries is None
    assert filters.project_year_min is None
