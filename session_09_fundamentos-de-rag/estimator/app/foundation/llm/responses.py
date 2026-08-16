"""Thin client over the OpenAI **Responses API** with strict structured output.

Why a second LLM entry point next to ``wrapper.py`` (LiteLLM + Instructor):
the Session 9 flow needs two things the wrapper cannot express — schema
enforcement at the API level (``strict``, so the model physically cannot emit
a field outside the schema) and ``reasoning.effort``, which replaces
``temperature`` on reasoning models. Instructor re-prompts on validation
errors; strict mode makes those errors impossible in the first place.

Scope is deliberately narrow: one method, no retries, no fallback between
providers. Retry policy belongs to the caller, which is the only one that knows
whether re-asking is worth the money (the generator retries once on invalid
citations; the reformulator falls back to plain rewriting instead).

``responses.parse`` is used rather than ``responses.create`` because it derives
the strict JSON schema from the Pydantic model itself — the hand-written
``schema=Model.model_json_schema()`` of the session material is not valid for
``strict: True`` without post-processing (it lacks ``additionalProperties:
false`` and does not mark every field required).
"""

from __future__ import annotations

import time
from typing import TypeVar

import structlog
from openai import OpenAI
from pydantic import BaseModel

log = structlog.get_logger()

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """The model returned no usable structured output (refusal, truncation…)."""


class ResponsesClient:
    """Structured, single-shot calls to the Responses API."""

    def __init__(self, client: OpenAI) -> None:
        self._client = client

    def parse(
        self,
        *,
        model: str,
        system_prompt: str,
        user_content: str,
        schema: type[T],
        reasoning_effort: str | None = None,
        stage: str = "llm",
    ) -> T:
        """Return an instance of ``schema`` produced by ``model``.

        ``reasoning_effort`` is only sent when provided: non-reasoning models
        reject the parameter outright.
        """
        kwargs: dict = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "text_format": schema,
        }
        if reasoning_effort:
            kwargs["reasoning"] = {"effort": reasoning_effort}

        started = time.perf_counter()
        response = self._client.responses.parse(**kwargs)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        parsed = response.output_parsed
        if parsed is None:
            # Refusal or an incomplete response: no partially-valid object is
            # ever handed back to the caller.
            raise StructuredOutputError(
                f"No structured output from {model} (status={response.status!r})"
            )

        usage = response.usage
        log.info(
            "responses_call_done",
            stage=stage,
            model=model,
            schema=schema.__name__,
            duration_ms=elapsed_ms,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            reasoning_effort=reasoning_effort,
        )
        return parsed

    def complete_text(self, *, model: str, system_prompt: str, user_content: str) -> str:
        """Free-form text completion. Only used by the reformulation fallback."""
        response = self._client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        return response.output_text.strip()
