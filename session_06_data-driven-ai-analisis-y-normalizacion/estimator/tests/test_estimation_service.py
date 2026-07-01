"""Unit tests for app/services/estimation.py.

Focuses on the two gaps that the endpoint-level tests leave uncovered:
- _exact_cache_key (pure function, never called because endpoint tests mock the
  whole service).
- EstimationService.estimate() (same reason).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import fakeredis
import pytest

from app.schemas.estimation import EstimationRequest, EstimationResult, EstimationResponse
from app.services.cache import EstimationCache
from app.services.estimation import EstimationService, _exact_cache_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_request() -> EstimationRequest:
    return EstimationRequest(
        description="CRM for the sales team with dashboard, reporting and email integration.",
        project_type="web_saas",
        detail_level="medium",
        output_format="phases_table",
    )


def _canned_result() -> EstimationResult:
    return EstimationResult(
        summary="Canned CRM estimation.",
        confidence_pct=70,
        phases=[
            {"name": "Discovery", "duration_weeks": 1, "cost_eur": 5_000, "summary": "Initial scoping and tech spike."},
            {"name": "Build", "duration_weeks": 5, "cost_eur": 20_000, "summary": "Core feature implementation."},
        ],
        total_duration_weeks=6,
        total_cost_eur=25_000,
    )


@pytest.fixture
def exact_cache() -> EstimationCache:
    return EstimationCache(fakeredis.FakeRedis(decode_responses=True), ttl=60)


@pytest.fixture
def fake_wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.primary_model = "gpt-4o-mini"
    wrapper.complete_structured.return_value = (
        _canned_result(),
        {"model": "gpt-4o-mini", "provider": "openai", "latency_ms": 50},
    )
    return wrapper


@pytest.fixture
def service(exact_cache: EstimationCache, fake_wrapper: MagicMock) -> EstimationService:
    return EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=exact_cache,
        semantic_cache=None,
        openai_client=None,
    )


# ---------------------------------------------------------------------------
# _exact_cache_key
# ---------------------------------------------------------------------------


def test_exact_cache_key_is_deterministic() -> None:
    req = _valid_request()
    assert _exact_cache_key(req, "v1", "gpt-4o-mini") == _exact_cache_key(req, "v1", "gpt-4o-mini")


def test_exact_cache_key_has_expected_prefix() -> None:
    req = _valid_request()
    assert _exact_cache_key(req, "v1", "gpt-4o-mini").startswith("estimation:v2:")


def test_exact_cache_key_differs_by_prompt_version() -> None:
    req = _valid_request()
    assert _exact_cache_key(req, "v1", "gpt-4o-mini") != _exact_cache_key(req, "v2", "gpt-4o-mini")


def test_exact_cache_key_differs_by_model() -> None:
    req = _valid_request()
    assert _exact_cache_key(req, "v1", "gpt-4o-mini") != _exact_cache_key(req, "v1", "gpt-4o")


# ---------------------------------------------------------------------------
# EstimationService.estimate() — exact cache hit
# ---------------------------------------------------------------------------


def test_estimate_exact_cache_hit_skips_llm(
    service: EstimationService,
    exact_cache: EstimationCache,
    fake_wrapper: MagicMock,
) -> None:
    req = _valid_request()
    key = _exact_cache_key(req, "v1", "gpt-4o-mini")
    exact_cache.set(key, {"result": _canned_result().model_dump(mode="json"), "prompt_version": "v1"})

    with patch("app.services.estimation.check_input"):
        result = service.estimate(req)

    assert result.cached is True
    assert result.result.total_cost_eur == 25_000
    fake_wrapper.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# EstimationService.estimate() — full pipeline (cache miss)
# ---------------------------------------------------------------------------


def test_estimate_cache_miss_calls_llm(
    service: EstimationService,
    fake_wrapper: MagicMock,
) -> None:
    with patch("app.services.estimation.check_input"):
        result = service.estimate(_valid_request())

    assert result.cached is False
    fake_wrapper.complete_structured.assert_called_once()


def test_estimate_cache_miss_populates_exact_cache(
    service: EstimationService,
    exact_cache: EstimationCache,
) -> None:
    req = _valid_request()
    with patch("app.services.estimation.check_input"):
        service.estimate(req)

    key = _exact_cache_key(req, "v1", "gpt-4o-mini")
    assert exact_cache.get(key) is not None


# ---------------------------------------------------------------------------
# EstimationService.estimate() — semantic cache hit
# ---------------------------------------------------------------------------


def test_estimate_semantic_cache_hit_skips_llm(
    exact_cache: EstimationCache,
    fake_wrapper: MagicMock,
) -> None:
    fake_semantic = MagicMock()
    fake_semantic.lookup.return_value = _canned_result()
    svc = EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=exact_cache,
        semantic_cache=fake_semantic,
        openai_client=None,
    )

    with patch("app.services.estimation.check_input"):
        result = svc.estimate(_valid_request())

    assert result.cached is True
    fake_wrapper.complete_structured.assert_not_called()


# ---------------------------------------------------------------------------
# EstimationService.estimate() — semantic cache write-through
# ---------------------------------------------------------------------------


def test_estimate_stores_in_semantic_cache_on_miss(
    exact_cache: EstimationCache,
    fake_wrapper: MagicMock,
) -> None:
    fake_semantic = MagicMock()
    fake_semantic.lookup.return_value = None
    svc = EstimationService(
        llm_wrapper=fake_wrapper,
        exact_cache=exact_cache,
        semantic_cache=fake_semantic,
        openai_client=None,
    )

    with patch("app.services.estimation.check_input"):
        svc.estimate(_valid_request())

    fake_semantic.store.assert_called_once()
