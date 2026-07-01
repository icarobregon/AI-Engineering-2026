"""Stress-test metrics for the CAG system.

Three metrics complementing the golden-dataset suite in ``evals/metrics.py``.
They operate on raw ``turn_observed`` dicts (or scalar values) rather than on
``(GoldenCase, EstimationResult)`` pairs, so they live in their own module.

The ``MetricResult`` dataclass is re-exported from the parent module to keep
the contract uniform — a single ``MetricResult`` shape across the whole eval
framework.
"""

from __future__ import annotations

from evals.metrics import MetricResult  # noqa: F401  — re-export for runners


class LatencyBudgetMetric:
    """1.0 if ``latency_ms`` <= ``budget_ms``; 0.0 otherwise.

    The budget defaults to 3 000 ms — a reasonable P95 SLA for an interactive
    estimation call. Adjust per deployment or SLA requirement.
    """

    name = "latency_budget"

    def __init__(self, budget_ms: int = 3_000) -> None:
        self.budget_ms = budget_ms

    def evaluate(self, turn: dict) -> MetricResult:
        latency = int(turn.get("latency_ms", 0))
        passed = latency <= self.budget_ms
        return MetricResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            details=f"latency {latency} ms {'<=' if passed else '>'} budget {self.budget_ms} ms",
        )


class CostBudgetMetric:
    """1.0 if ``cost_usd`` <= ``budget_usd``; 0.0 otherwise.

    Default budget is $0.05 per turn — generous enough for a single gpt-4o-mini
    call with a long context, tight enough to surface expensive turns.
    """

    name = "cost_budget"

    def __init__(self, budget_usd: float = 0.05) -> None:
        self.budget_usd = budget_usd

    def evaluate(self, turn: dict) -> MetricResult:
        cost = float(turn.get("cost_usd", 0.0))
        passed = cost <= self.budget_usd
        return MetricResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            details=(
                f"cost ${cost:.6f} {'<=' if passed else '>'} budget ${self.budget_usd:.4f}"
            ),
        )


class MemoryDriftMetric:
    """Checks that ``fact_to_remember`` appears verbatim in ``response_text``.

    Determinism over sophistication: exact case-insensitive substring match.
    A passing score means the LLM carried the fact forward in its response.
    A failing score is a memory-drift event — the model forgot or dropped it.

    ``fact_to_remember`` is the fact declared by the PREVIOUS turn (the thing
    the model should still remember). Pass an empty string or ``None`` when
    there is no prior fact to check — the metric returns a neutral pass.
    """

    name = "memory_drift"

    def evaluate(
        self,
        response_text: str,
        fact_to_remember: str | None,
    ) -> MetricResult:
        if not fact_to_remember:
            return MetricResult(
                name=self.name,
                score=1.0,
                passed=True,
                details="no fact declared in previous turn — skipped",
            )
        found = fact_to_remember.lower() in response_text.lower()
        return MetricResult(
            name=self.name,
            score=1.0 if found else 0.0,
            passed=found,
            details=(
                f"fact {'FOUND' if found else 'NOT FOUND'} in response: {fact_to_remember!r}"
            ),
        )
