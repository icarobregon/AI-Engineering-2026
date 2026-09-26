"""How every agent in this package talks to the model.

Two helpers, shared by the specialists and by the supervisor so that a fix to
either applies to both — a second copy of this is how the script and the service
drifted apart in Session 13 and cost a deliverable run.

``structured_call`` goes through the project's ``LLMWrapper`` rather than a raw
provider client: this layer is not the one that gets to pick a vendor, and the
wrapper is where the retries, the fallback model and the cost accounting live.
It runs the call on a worker thread because ``complete_structured`` is
synchronous (Instructor + LiteLLM) and this graph shares its event loop with the
retrieval queries and the checkpoint writes.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def structured_call(
    llm: Any,
    *,
    system_prompt: str,
    user_message: str,
    model: str,
    response_model,
    effort: str | None = None,
    max_tokens: int | None = None,
):
    """Ask the model for one typed object. Returns ``(parsed, meta)``."""
    return await asyncio.to_thread(
        llm.complete_structured,
        system_prompt=system_prompt,
        user_message=user_message,
        response_model=response_model,
        model_override=model,
        reasoning_effort=effort,
        **({"max_tokens": max_tokens} if max_tokens else {}),
    )


def stamp_llm(span, meta: dict) -> None:
    """Put on the span what the call cost, when it reported it.

    Only keys actually present are stamped: an attribute that is always None
    reads like an instrumented number and is worse than an absent one, because a
    dashboard will happily sum it to zero. The first version stamped cost and
    tokens unconditionally — and complete_structured reports neither, so every
    node span carried two null numbers.
    """
    for key, value in (
        ("model", meta.get("model")),
        ("latency_ms", meta.get("latency_ms")),
        ("llm_cost_usd", meta.get("cost_usd")),
        ("total_tokens", (meta.get("usage") or {}).get("total_tokens")),
    ):
        if value is not None:
            span.set_attribute(key, value)
