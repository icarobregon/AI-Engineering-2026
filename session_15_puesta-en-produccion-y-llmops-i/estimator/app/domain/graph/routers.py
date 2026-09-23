"""The two ways the supervisor's one question can be answered.

The supervisor asks a closed question — one of two agents, and why — and does
not care who answers it. A chat model answers it as typed JSON; TypeSafe's Jev
answers it as a choice with a probability and no prose at all. Both are reduced
here to the same ``(next_agent, reason, meta)``, so the node keeps its single
exit and its single ``AGENT_NAMES`` guard.

Neither implementation imports a client: they receive one. ``app/domain/graph``
may not reach the composition root (ARCHITECTURE.md §3), which is the same rule
that made ``search_backend`` an argument, and is what lets a test drive either
router with a two-line double.
"""

from __future__ import annotations

from typing import Any, Callable

import structlog

from app.domain.graph.llm import structured_call
from app.domain.graph.supervisor import SupervisorDecision, compose_supervisor_prompt

log = structlog.get_logger()


def build_ask_router(
    *,
    llm: Any,
    resolve_model: Callable[[], str],
    text_model_default: str,
    decision_client: Any = None,
) -> Callable[..., Any]:
    """Return the ``ask_router`` the supervisor is built with.

    ``resolve_model`` is called ON EVERY DECISION, not once here. That is the
    whole reason the supervisor stopped taking a model string: the graph is
    compiled once per process (main.py), so a model captured at wiring time can
    never change, and the Settings screen would write an override to Redis that
    silently did nothing — against the no-restart contract the config endpoint
    itself advertises.
    """
    if decision_client is not None and decision_client.handles(text_model_default):
        # The .env default is the floor every degraded path lands on, so it has
        # to be a model that can write prose. Failing here is deliberate: the
        # alternative is discovering it during an outage, which is exactly when
        # the fallback is the only thing left.
        raise ValueError(
            f"GRAPH_SUPERVISOR_MODEL={text_model_default!r} is a decision model. "
            "The .env default is the fallback for the runtime override and must "
            "be a text model; select the decision model from Settings instead."
        )

    async def _ask_text(model: str, state_text: str, instructions, criteria, bias):
        parsed, meta = await structured_call(
            llm,
            system_prompt=compose_supervisor_prompt(instructions, criteria, bias),
            user_message=state_text,
            model=model,
            response_model=SupervisorDecision,
        )
        return parsed.next_agent, parsed.reason, meta

    async def ask_router(
        *,
        state_text: str,
        instructions: str,
        criteria: dict[str, str],
        bias: str,
        facts: str,
    ):
        model = resolve_model()

        if decision_client is not None and decision_client.handles(model):
            try:
                choice, meta = await decision_client.choose(
                    state=state_text,
                    model=model,
                    # The bias is not attached to either option, so it rides with
                    # the instructions — the only field the evaluate endpoint
                    # offers that is not part of a criterion.
                    instructions=f"{instructions}\n\n{bias}",
                    criteria=criteria,
                )
            except Exception as exc:  # noqa: BLE001 — degrade, never fail the run
                log.warning("supervisor_decision_model_failed", model=model, error=str(exc)[:200])
                agent, reason, meta = await _ask_text(
                    text_model_default, state_text, instructions, criteria, bias
                )
                # Named in the reason, because the audit table is where a human
                # reads this hop and "needs review" looks identical whether the
                # router chose it or the vendor was unreachable.
                return agent, f"{model} no respondió; decidió {text_model_default}: {reason}", meta
            return choice, _decision_reason(facts, model, choice, meta), meta

        if decision_client is None and model != text_model_default and _looks_like_decision(model):
            # A stale override outlives the key that made it legal: the store
            # resolves `get(key) or default(key)` with nothing revalidating it,
            # and the endpoint only validates at write time. Without this the
            # name would reach the chat path, which sends everything non-
            # Anthropic with the OpenAI key.
            log.error("supervisor_decision_model_unconfigured", model=model)
            model = text_model_default

        return await _ask_text(model, state_text, instructions, criteria, bias)

    return ask_router


def _looks_like_decision(model: str) -> bool:
    """Shape test for the no-client case, where there is no client to ask."""
    return model.startswith("jev-")


def _decision_reason(facts: str, model: str, choice: str, meta: dict) -> str:
    """The trail entry for a router that returns no prose.

    The counts come from the state and the probability from the answer, so the
    sentence a reviewer reads is at least as specific as the chat model's — and
    the half that matters cannot be wrong, because nothing generated it.
    """
    probability = (meta.get("probabilities") or {}).get(choice)
    suffix = f" (p={probability:.2f})" if isinstance(probability, (int, float)) else ""
    return f"{facts}; {model} enrutó a {choice}{suffix}"
