"""Unit tests for evals/stress/metrics.py — Bloque 4."""

from __future__ import annotations

import pytest

from evals.stress.metrics import CostBudgetMetric, LatencyBudgetMetric, MemoryDriftMetric


# ---------------------------------------------------------------------------
# LatencyBudgetMetric
# ---------------------------------------------------------------------------


class TestLatencyBudgetMetric:
    def test_passes_when_equal_to_budget(self):
        m = LatencyBudgetMetric(budget_ms=3000)
        r = m.evaluate({"latency_ms": 3000})
        assert r.passed
        assert r.score == 1.0

    def test_passes_when_below_budget(self):
        m = LatencyBudgetMetric(budget_ms=3000)
        r = m.evaluate({"latency_ms": 1500})
        assert r.passed
        assert r.score == 1.0

    def test_fails_when_above_budget(self):
        m = LatencyBudgetMetric(budget_ms=3000)
        r = m.evaluate({"latency_ms": 3001})
        assert not r.passed
        assert r.score == 0.0

    def test_custom_budget(self):
        m = LatencyBudgetMetric(budget_ms=500)
        assert not m.evaluate({"latency_ms": 501}).passed
        assert m.evaluate({"latency_ms": 499}).passed

    def test_missing_key_defaults_to_zero(self):
        m = LatencyBudgetMetric(budget_ms=1000)
        r = m.evaluate({})
        assert r.passed  # 0 <= 1000

    def test_name(self):
        assert LatencyBudgetMetric.name == "latency_budget"


# ---------------------------------------------------------------------------
# CostBudgetMetric
# ---------------------------------------------------------------------------


class TestCostBudgetMetric:
    def test_passes_when_at_budget(self):
        m = CostBudgetMetric(budget_usd=0.05)
        r = m.evaluate({"cost_usd": 0.05})
        assert r.passed
        assert r.score == 1.0

    def test_passes_when_below_budget(self):
        m = CostBudgetMetric(budget_usd=0.05)
        r = m.evaluate({"cost_usd": 0.01})
        assert r.passed

    def test_fails_when_above_budget(self):
        m = CostBudgetMetric(budget_usd=0.05)
        r = m.evaluate({"cost_usd": 0.0501})
        assert not r.passed
        assert r.score == 0.0

    def test_custom_budget(self):
        m = CostBudgetMetric(budget_usd=0.001)
        assert not m.evaluate({"cost_usd": 0.002}).passed
        assert m.evaluate({"cost_usd": 0.0009}).passed

    def test_missing_key_defaults_to_zero(self):
        m = CostBudgetMetric(budget_usd=0.05)
        r = m.evaluate({})
        assert r.passed  # 0.0 <= 0.05

    def test_name(self):
        assert CostBudgetMetric.name == "cost_budget"


# ---------------------------------------------------------------------------
# MemoryDriftMetric
# ---------------------------------------------------------------------------


class TestMemoryDriftMetric:
    def test_fact_present_passes(self):
        m = MemoryDriftMetric()
        r = m.evaluate("El proyecto requiere autenticación de doble factor.", "doble factor")
        assert r.passed
        assert r.score == 1.0

    def test_fact_absent_fails(self):
        m = MemoryDriftMetric()
        r = m.evaluate("El proyecto requiere autenticación básica.", "doble factor")
        assert not r.passed
        assert r.score == 0.0

    def test_case_insensitive(self):
        m = MemoryDriftMetric()
        assert m.evaluate("Multi-Tenant architecture.", "multi-tenant").passed
        assert m.evaluate("MULTI-TENANT architecture.", "multi-tenant").passed

    def test_none_fact_skipped(self):
        m = MemoryDriftMetric()
        r = m.evaluate("Cualquier texto.", None)
        assert r.passed
        assert r.score == 1.0

    def test_empty_string_fact_skipped(self):
        m = MemoryDriftMetric()
        r = m.evaluate("Cualquier texto.", "")
        assert r.passed
        assert r.score == 1.0

    def test_fact_as_substring(self):
        m = MemoryDriftMetric()
        # Fact is a substring of a longer phrase in the response.
        r = m.evaluate(
            "Hemos incluido exportación a PDF y Excel en el módulo de reporting.",
            "PDF y Excel",
        )
        assert r.passed

    def test_name(self):
        assert MemoryDriftMetric.name == "memory_drift"


# ---------------------------------------------------------------------------
# MetricResult re-export
# ---------------------------------------------------------------------------


def test_metric_result_reexport():
    from evals.stress.metrics import MetricResult

    r = MetricResult(name="x", score=0.5, passed=False, details="test")
    assert r.name == "x"
    assert r.score == 0.5
