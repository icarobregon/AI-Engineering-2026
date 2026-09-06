"""Doubles for the estimation graph: no network, no database, no API key."""

from __future__ import annotations

import pytest

from app.domain.graph.schemas import (
    ClassifiedComponent,
    ComponentList,
    DraftEstimate,
    EstimatedComponent,
    RequirementList,
)


class FakeLLM:
    """Answers each node's response_model with a scripted result.

    Records every call so a test can assert which model a node asked for — the
    graph runs the mechanical steps on the cheap model and the estimate on the
    strong one, and that is a wiring decision worth pinning.
    """

    def __init__(self, *, estimate: DraftEstimate | None = None, components=None):
        self.calls: list[dict] = []
        self._estimate = estimate
        self._components = components

    def complete_structured(self, *, system_prompt, user_message, response_model, **kwargs):
        self.calls.append(
            {
                "model": kwargs.get("model_override"),
                "response_model": response_model,
                "user_message": user_message,
                "max_tokens": kwargs.get("max_tokens"),
                "reasoning_effort": kwargs.get("reasoning_effort"),
            }
        )
        meta = {
            "model": kwargs.get("model_override"),
            "cost_usd": 0.002,
            "usage": {"total_tokens": 120},
        }
        if response_model is RequirementList:
            return RequirementList(requirements=["backend de pedidos", "app de repartidores"]), meta
        if response_model is ComponentList:
            return ComponentList(
                components=self._components
                or [
                    ClassifiedComponent(
                        name="Backend de negocio",
                        category="backend",
                        search_query="logistics order management backend with REST API",
                    ),
                    ClassifiedComponent(
                        name="App móvil",
                        category="mobile",
                        search_query="courier mobile app with offline sync",
                    ),
                ]
            ), meta
        return (
            self._estimate
            or DraftEstimate(
                project="RUTA",
                components=[
                    EstimatedComponent(
                        component_id="c1",
                        name="Backend de negocio",
                        estimated_hours=90.0,
                        grounded=True,
                        rationale="1 analogue",
                    ),
                    EstimatedComponent(
                        component_id="c2",
                        name="App móvil",
                        estimated_hours=82.0,
                        grounded=True,
                        rationale="1 analogue",
                    ),
                ],
                total_hours=172.0,
                notes="",
            )
        ), meta


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_backend():
    """Retrieval double: one historical module per query, recording the queries."""
    seen: list[str] = []

    async def backend(query, **kwargs):
        seen.append(query)
        return [
            {"budget_id": "TASK-2024-0018/Fleet & Routing", "estimated_hours": 90},
            {"budget_id": "TASK-2023-0050/Frontend / UX", "estimated_hours": 82},
        ]

    backend.seen = seen
    return backend
