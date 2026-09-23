"""Doubles for the multi-agent system: no network, no database, no API key.

The three Session 12 tools are used for REAL here — they are deterministic
Python and faking them would test the fake. Only the model and the retrieval
backend are doubled, which is exactly the boundary the system draws.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domain.graph.agents import build_agents, build_finalize
from app.domain.graph.build import build_graph
from app.domain.graph.hitl import build_human_review_gate
from app.domain.graph.schemas import (
    ClassifiedComponent,
    ComponentList,
    ComponentNarrative,
    EstimateNarrative,
    RequirementList,
)
from app.domain.graph.routers import build_ask_router
from app.domain.graph.supervisor import SupervisorDecision, build_supervisor
from app.generation.agentic.agent_tools import (
    calculate_estimate,
    search_budgets,
    validate_estimate,
)

TRANSCRIPT = "Reunión: necesitamos un backend de pedidos y una app para repartidores."


class FakeLLM:
    """Answers each agent's response_model with a scripted result.

    Records every call so a test can assert which model an agent asked for — the
    mechanical steps run on the cheap model, the estimate's prose on the strong
    one and the routing decision on the cheap one, and that is a wiring decision
    worth pinning.
    """

    def __init__(self, *, narrative: EstimateNarrative | None = None, components=None):
        self.calls: list[dict] = []
        self._narrative = narrative
        self._components = components
        # What the supervisor's one model-routed decision will answer.
        self.route_to = "human_review_gate"

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
            # `is None`, not falsiness: a scripted EMPTY component list is a real
            # case (a meeting with nothing concrete in it) and must not fall back
            # to the default two.
            return ComponentList(
                components=self._components
                if self._components is not None
                else [
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
        if response_model is SupervisorDecision:
            return (
                SupervisorDecision(next_agent=self.route_to, reason="scripted"),
                meta,
            )
        return (
            self._narrative
            or EstimateNarrative(
                project="RUTA",
                components=[
                    ComponentNarrative(component_id="c1", rationale="1 analogue"),
                    ComponentNarrative(component_id="c2", rationale="1 analogue"),
                ],
                notes="",
            )
        ), meta


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def fake_backend():
    """Retrieval double: two historical modules per query, recording the queries."""
    seen: list[str] = []

    async def backend(query, **kwargs):
        seen.append(query)
        return [
            {
                "budget_id": "TASK-2024-0018/Fleet & Routing",
                "estimated_hours": 90,
                "distance": 0.15,
            },
            {
                "budget_id": "TASK-2023-0050/Frontend / UX",
                "estimated_hours": 82,
                "distance": 0.25,
            },
        ]

    backend.seen = seen
    return backend


@pytest.fixture
def partial_backend():
    """A corpus that covers the first component and has never seen the second."""
    seen: list[str] = []

    async def backend(query, **kwargs):
        seen.append(query)
        if len(seen) > 1:
            return []

        return [
            {
                "budget_id": "TASK-2024-0018/Fleet & Routing",
                "estimated_hours": 90,
                "distance": 0.15,
            },
            {"budget_id": "TASK-2023-0050/Frontend / UX", "estimated_hours": 82, "distance": 0.25},
        ]

    backend.seen = seen
    return backend


@pytest.fixture
def empty_backend():
    """A corpus with no precedent for anything — the edge case the gate exists for."""

    async def backend(query, **kwargs):
        return []

    return backend


def build_test_agents(fake_llm, backend, **overrides) -> dict:
    """The same agent map the composition root builds, with the doubles bound."""
    agents = build_agents(
        llm=fake_llm,
        search_backend=backend,
        search_tool=search_budgets,
        calculate_tool=calculate_estimate,
        validate_tool=validate_estimate,
        fast_model=overrides.get("fast_model", "gpt-5-mini"),
        estimate_model=overrides.get("estimate_model", "gpt-5"),
        reasoning_effort=overrides.get("reasoning_effort", "medium"),
        estimate_max_tokens=overrides.get("estimate_max_tokens", 16000),
    )
    max_routing_steps = overrides.get("max_routing_steps", 8)
    supervisor_model = overrides.get("supervisor_model", "gpt-5-mini")
    agents["supervisor"] = build_supervisor(
        ask_router=overrides.get("ask_router")
        or build_ask_router(
            llm=fake_llm,
            resolve_model=lambda: supervisor_model,
            text_model_default=supervisor_model,
            decision_client=overrides.get("decision_client"),
        ),
        max_routing_steps=max_routing_steps,
    )
    agents["human_review_gate"] = build_human_review_gate(
        confidence_threshold=overrides.get("confidence_threshold", 0.7),
        band_tolerance=overrides.get("band_tolerance", 0.25),
    )
    agents["finalize"] = build_finalize()
    return agents


def build_test_graph(fake_llm, backend, checkpointer=None, **overrides):
    return build_graph(
        build_test_agents(fake_llm, backend, **overrides),
        checkpointer=checkpointer or MemorySaver(),
    )


def start(thread_id: str, transcript: str = TRANSCRIPT) -> dict:
    """The input the router sends: new data only, never an accumulator."""
    return {"transcript": transcript, "estimation_id": thread_id}


def config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}
