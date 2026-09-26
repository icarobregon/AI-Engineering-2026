"""LiteLLM-backed wrapper that adds provider fallback, exact-match cache, cost tracking,
and structured logging to every LLM call in the estimator.

Design notes
------------
- The wrapper exposes two primitives:
  - ``complete()``: legacy free-text answer (kept for tests that depend on it).
  - ``complete_structured()``: returns a validated Pydantic model via Instructor,
    re-prompting on validator errors up to ``max_retries`` times.
- The Router is configured with two deployments under the same ``model_name``
  ("estimator") so LiteLLM can switch from primary to fallback transparently.
  When the caller overrides the model per-request we bypass the Router and call
  ``litellm.completion`` directly — that path has no fallback by design.
- ``primary_model``/``fallback_model`` are PROPERTIES backed by the runtime
  config store (Redis): the Settings UI can switch models mid-session. The
  Router keeps the *initial* (settings) deployments — it is never rebuilt at
  request time (thread-safety) — so an active runtime override routes through
  the direct ``litellm.completion`` path, with the same no-fallback semantics
  as a per-call ``model_override``.
"""

from __future__ import annotations

import re
import time
from typing import Any, TypeVar

import instructor
import litellm
import structlog
from litellm import Router
from pydantic import BaseModel

from app.foundation.llm.runtime_config import RuntimeModelConfig
from app.generation.cag.exact import EstimationCache

log = structlog.get_logger()

_MAX_LOGGED_ERROR_CHARS = 500


def _failure_fields(exc: Exception) -> dict[str, Any]:
    """Bounded, structured description of a failed call.

    ``InstructorRetryException.__str__`` is not a message: it renders EVERY
    failed attempt with its full completion, so a six-round failure pushed tens
    of KB into a single log line — including the entire contents of the
    estimations that failed. Truncating alone would lose the part that actually
    helps, so the numbers that matter are lifted into their own fields: how many
    attempts were spent and what they cost.
    """
    fields: dict[str, Any] = {
        "error_type": type(exc).__name__,
        "error": str(exc)[:_MAX_LOGGED_ERROR_CHARS],
    }
    if (attempts := getattr(exc, "n_attempts", None)) is not None:
        fields["attempts"] = attempts
    if (usage := getattr(exc, "total_usage", None)) is not None:
        fields["wasted_tokens_in"] = getattr(usage, "prompt_tokens", None)
        fields["wasted_tokens_out"] = getattr(usage, "completion_tokens", None)
    return fields


# Cost per 1M tokens (USD), standard API tier — no batch, no cache-hit, no fast
# mode. Curated by hand alongside AVAILABLE_MODELS in app/config.py: a model that
# is selectable but missing here is priced at zero, and a zero cost is worse than
# no cost at all (see ``_usage_from``). Provenance and date live next to the
# catalogue, in MODEL_CATALOG_GENERATED_AT.
#
# Aliases carry their own row on purpose: the lookup uses the name we ASKED for,
# so ``claude-sonnet-4-5`` and ``claude-sonnet-4-5-20250929`` both need pricing
# even though they are the same model.
MODEL_COSTS: dict[str, dict[str, float]] = {
    # --- OpenAI · GPT-4 ---
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    # --- OpenAI · GPT-5 ---
    "gpt-5-nano": {"input": 0.05, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
    "gpt-5": {"input": 1.25, "output": 10.00},
    "gpt-5-pro": {"input": 15.00, "output": 120.00},
    "gpt-5.1": {"input": 1.25, "output": 10.00},
    "gpt-5.2": {"input": 1.75, "output": 14.00},
    "gpt-5.2-pro": {"input": 21.00, "output": 168.00},
    "gpt-5.4-nano": {"input": 0.20, "output": 1.25},
    "gpt-5.4-mini": {"input": 0.75, "output": 4.50},
    "gpt-5.4": {"input": 2.50, "output": 15.00},
    "gpt-5.4-pro": {"input": 30.00, "output": 180.00},
    "gpt-5.5": {"input": 5.00, "output": 30.00},
    "gpt-5.5-pro": {"input": 30.00, "output": 180.00},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
    "gpt-5.6-terra": {"input": 2.00, "output": 12.00},
    "gpt-5.6-sol": {"input": 4.00, "output": 20.00},
    # --- OpenAI · GPT-6 ---
    "gpt-6-astra": {"input": 10.00, "output": 50.00},
    # --- OpenAI · razonadores de la serie o ---
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "o3": {"input": 2.00, "output": 8.00},
    "o1": {"input": 15.00, "output": 60.00},
    "o1-pro": {"input": 150.00, "output": 600.00},
    # --- Anthropic · Haiku ---
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    # --- Anthropic · Sonnet ---
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    # --- Anthropic · Opus ---
    "claude-opus-4-5-20251101": {"input": 5.00, "output": 25.00},
    "claude-opus-4-6": {"input": 5.00, "output": 25.00},
    "claude-opus-4-7": {"input": 5.00, "output": 25.00},
    "claude-opus-4-8": {"input": 5.00, "output": 25.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    # --- Anthropic · Fable ---
    "claude-fable-5": {"input": 10.00, "output": 50.00},
    "claude-fable-5-1": {"input": 10.00, "output": 50.00},
}


T = TypeVar("T", bound=BaseModel)


def _usage_from(result: Any, target_model: str) -> dict[str, Any]:
    """Read token usage and cost off an Instructor result, if it carries them.

    The price is looked up by the model we ASKED for, not the one the API says it
    served: providers answer with a dated snapshot (``gpt-5-mini-2025-08-07``)
    that is not a key in the price table, and the lookup's 0.0 default then
    reports every call as free. A cost of zero is worse than no cost at all —
    it is a number, and a dashboard will believe it.
    """
    usage = getattr(getattr(result, "_raw_response", None), "usage", None)
    if usage is None:
        return {}
    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = getattr(usage, "completion_tokens", 0) or 0
    model = target_model
    return {
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": getattr(usage, "total_tokens", input_tokens + output_tokens) or 0,
        },
        "cost_usd": _estimate_cost(model, input_tokens, output_tokens),
    }


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    base = _normalise_model_name(model)
    costs = MODEL_COSTS.get(base) or MODEL_COSTS.get(model) or {"input": 0.0, "output": 0.0}
    return round((tokens_in * costs["input"] + tokens_out * costs["output"]) / 1_000_000, 6)


_O_SERIES = re.compile(r"^o\d")


def _normalise_model_name(model: str) -> str:
    """Strip provider prefixes like ``anthropic/`` that LiteLLM may emit."""
    return model.split("/", 1)[1] if "/" in model else model


def _provider_from_model(model: str) -> str:
    """Infer the provider from the model name.

    The o-series is matched by shape (``o`` + digit) rather than by listing
    ``o1``/``o3``: an unmatched name falls through to "unknown", and "unknown"
    has no key field, so ``/api/v1/config/models`` would drop the model from the
    catalogue without a word. ``o4-mini`` was doing exactly that.
    """
    name = _normalise_model_name(model).lower()
    if name.startswith("claude"):
        return "anthropic"
    if name.startswith("gpt") or _O_SERIES.match(name):
        return "openai"
    return "unknown"


class LLMWrapper:
    """Unified LLM client with cache, fallback, and cost tracking."""

    def __init__(
        self,
        *,
        openai_api_key: str | None,
        anthropic_api_key: str | None,
        primary_model: str,
        fallback_model: str,
        timeout: int,
        num_retries: int,
        cache: EstimationCache,
        runtime_config: RuntimeModelConfig | None = None,
    ):
        self.openai_api_key = openai_api_key
        self.anthropic_api_key = anthropic_api_key
        # Initial (settings) models: they seed the Router deployments and act
        # as the fallback when no runtime config store is wired (tests).
        self._initial_primary_model = primary_model
        self._initial_fallback_model = fallback_model
        self._runtime_config = runtime_config
        self.timeout = timeout
        self.num_retries = num_retries
        self.cache = cache

        self.router = Router(
            model_list=[
                {
                    "model_name": "estimator",
                    "litellm_params": {
                        "model": primary_model,
                        "api_key": openai_api_key,
                        "timeout": timeout,
                    },
                },
                {
                    # Its own alias, and that is the whole point: with both
                    # deployments named "estimator" the fallback below pointed
                    # the alias at ITSELF, so a provider outage just retried the
                    # same dead provider. The configuration promised resilience
                    # and delivered none.
                    "model_name": "estimator-fallback",
                    "litellm_params": {
                        "model": fallback_model,
                        "api_key": anthropic_api_key,
                        "timeout": timeout,
                    },
                },
            ],
            fallbacks=[{"estimator": ["estimator-fallback"]}],
            num_retries=num_retries,
        )

        # Instructor wraps ``litellm.completion`` so we can call any of the
        # underlying providers with the same ``response_model=`` API.
        self._instructor = instructor.from_litellm(litellm.completion)

    # ------------------------------------------------------------------
    # Effective models (runtime override > settings default)
    # ------------------------------------------------------------------

    @property
    def primary_model(self) -> str:
        """The model every non-overridden call uses, resolved per call so a
        runtime override (Settings UI) takes effect immediately."""
        if self._runtime_config is not None:
            return self._runtime_config.effective("PRIMARY_MODEL")
        return self._initial_primary_model

    @property
    def fallback_model(self) -> str:
        if self._runtime_config is not None:
            return self._runtime_config.effective("FALLBACK_MODEL")
        return self._initial_fallback_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        *,
        system_prompt: str,
        user_message: str,
        model_override: str | None = None,
        max_tokens: int = 4000,
        thinking_budget: int | None = None,
    ) -> dict[str, Any]:
        """Single LLM call returning a free-text answer. Kept for tests."""
        cache_key_model = model_override or self.primary_model
        cache_key = EstimationCache.make_key(
            system_prompt=system_prompt,
            user_message=user_message,
            model=cache_key_model,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
        )
        cached = self.cache.get(cache_key)
        if cached:
            return {**cached, "cache_hit": True}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        kwargs = self._build_call_kwargs(
            messages=messages,
            max_tokens=max_tokens,
            thinking_budget=thinking_budget,
            model_override=model_override,
        )

        log.info(
            "llm_call_started",
            mode="blocking",
            model=model_override or self.primary_model,
        )
        t0 = time.perf_counter()
        try:
            response = self._dispatch(model_override=model_override, **kwargs)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "llm_call_failed",
                latency_ms=latency_ms,
                **_failure_fields(exc),
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        result = self._normalise_response(response, latency_ms=latency_ms)
        log.info(
            "llm_call_completed",
            model=result["model"],
            provider=result["provider"],
            input_tokens=result["usage"]["input_tokens"],
            output_tokens=result["usage"]["output_tokens"],
            cost_usd=result["cost_usd"],
            latency_ms=latency_ms,
            finish_reason=result["finish_reason"],
        )
        self.cache.set(cache_key, result)
        return {**result, "cache_hit": False}

    def complete_structured_chat(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[T],
        model_override: str | None = None,
        max_tokens: int = 4000,
        max_retries: int = 6,
        reasoning_effort: str | None = None,
    ) -> tuple[T, dict[str, Any]]:
        """Conversational variant of :meth:`complete_structured`.

        Accepts a pre-built ``messages`` list (system + N user/assistant pairs +
        current user). Bypasses the Router for deterministic routing — same
        rationale as ``complete_structured``: the LiteLLM Router would
        round-robin between deployments and could non-deterministically pick
        the fallback. Instructor handles re-prompts when Pydantic validators
        raise.
        """
        target_model = model_override or self.primary_model
        api_key = (
            self.anthropic_api_key
            if _provider_from_model(target_model) == "anthropic"
            else self.openai_api_key
        )

        log.info(
            "llm_structured_chat_started",
            model=target_model,
            response_model=response_model.__name__,
            messages=len(messages),
        )
        # Reasoning models (gpt-5 family) accept ``reasoning_effort``; LiteLLM
        # forwards it and translates ``max_tokens`` to ``max_completion_tokens``.
        extra: dict[str, Any] = {}
        if reasoning_effort is not None:
            extra["reasoning_effort"] = reasoning_effort

        t0 = time.perf_counter()
        try:
            result = self._instructor.chat.completions.create(
                model=target_model,
                api_key=api_key,
                timeout=self.timeout,
                messages=messages,
                response_model=response_model,
                max_tokens=max_tokens,
                max_retries=max_retries,
                **extra,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "llm_structured_chat_failed",
                latency_ms=latency_ms,
                **_failure_fields(exc),
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        meta = {
            "model": _normalise_model_name(target_model),
            "provider": _provider_from_model(target_model),
            "latency_ms": latency_ms,
            # Same reading as the single-shot variant. Without it every
            # conversational turn reported 0 tokens and $0.
            **_usage_from(result, target_model),
        }
        log.info(
            "llm_structured_chat_completed",
            model=meta["model"],
            provider=meta["provider"],
            latency_ms=latency_ms,
            cost_usd=meta.get("cost_usd"),
        )
        return result, meta

    def complete_structured(
        self,
        *,
        system_prompt: str,
        user_message: str,
        response_model: type[T],
        model_override: str | None = None,
        max_tokens: int = 4000,
        max_retries: int = 6,
        reasoning_effort: str | None = None,
        timeout: int | None = None,
    ) -> tuple[T, dict[str, Any]]:
        """Run the LLM with Instructor and return ``(model_instance, meta)``.

        ``timeout`` overrides the wrapper's own deadline for this call. It exists
        because one deadline cannot fit both shapes of call this service makes: a
        chat-shaped completion answers in seconds, and a reasoning model at high
        effort spends minutes thinking before it emits a token.

        ``meta`` includes ``model``, ``provider`` and ``latency_ms``. Instructor
        re-prompts the LLM up to ``max_retries`` times when a Pydantic validator
        raises, feeding the ``ValueError`` message back to the model.

        Streaming bypasses are not relevant here — the entire model is built
        atomically by Instructor before this function returns.
        """
        target_model = model_override or self.primary_model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        api_key = (
            self.anthropic_api_key
            if _provider_from_model(target_model) == "anthropic"
            else self.openai_api_key
        )

        log.info(
            "llm_structured_call_started",
            model=target_model,
            response_model=response_model.__name__,
        )
        extra: dict[str, Any] = {}
        if reasoning_effort is not None:
            extra["reasoning_effort"] = reasoning_effort

        t0 = time.perf_counter()
        try:
            result = self._instructor.chat.completions.create(
                model=target_model,
                api_key=api_key,
                timeout=timeout or self.timeout,
                messages=messages,
                response_model=response_model,
                max_tokens=max_tokens,
                max_retries=max_retries,
                **extra,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            log.error(
                "llm_structured_call_failed",
                latency_ms=latency_ms,
                **_failure_fields(exc),
            )
            raise

        latency_ms = int((time.perf_counter() - t0) * 1000)
        meta = {
            "model": _normalise_model_name(target_model),
            "provider": _provider_from_model(target_model),
            "latency_ms": latency_ms,
            # Usage rides on the raw completion Instructor keeps beside the parsed
            # model. It is read defensively because it is a private attribute: a
            # missing one costs the cost figure, never the call. Session 13 puts
            # this on every node's span, which is what turns "what does an
            # estimate cost" into a query instead of an estimate.
            **_usage_from(result, target_model),
        }
        log.info(
            "llm_structured_call_completed",
            model=meta["model"],
            provider=meta["provider"],
            latency_ms=latency_ms,
            cost_usd=meta.get("cost_usd"),
        )
        return result, meta

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_call_kwargs(
        self,
        *,
        messages: list[dict],
        max_tokens: int,
        thinking_budget: int | None,
        model_override: str | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if thinking_budget is not None:
            target_model = model_override or self.primary_model
            if _provider_from_model(target_model) == "anthropic":
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
                kwargs["max_tokens"] = max(max_tokens, thinking_budget + 1024)
            else:
                log.warning(
                    "thinking_budget_ignored_for_provider",
                    provider=_provider_from_model(target_model),
                    model=target_model,
                )
        return kwargs

    def _dispatch(self, *, model_override: str | None, **kwargs: Any) -> Any:
        """Call the Router (with fallback) or LiteLLM directly when the caller
        wants a specific model.

        A runtime primary override behaves like a per-call ``model_override``:
        the Router deployments are frozen at construction (never rebuilt at
        request time), so when the effective primary differs from the one the
        Router was built with, the call goes direct — no automatic fallback.
        """
        if model_override:
            return self._direct_completion(model=model_override, **kwargs)
        effective_primary = self.primary_model
        if effective_primary != self._initial_primary_model:
            return self._direct_completion(model=effective_primary, **kwargs)
        return self.router.completion(model="estimator", **kwargs)

    def _direct_completion(self, *, model: str, **kwargs: Any) -> Any:
        api_key = (
            self.anthropic_api_key
            if _provider_from_model(model) == "anthropic"
            else self.openai_api_key
        )
        return litellm.completion(
            model=model,
            api_key=api_key,
            timeout=self.timeout,
            num_retries=self.num_retries,
            **kwargs,
        )

    @staticmethod
    def _normalise_response(response: Any, *, latency_ms: int) -> dict[str, Any]:
        choice = response.choices[0]
        finish_reason = (choice.finish_reason or "stop").lower()
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", input_tokens + output_tokens) or (
            input_tokens + output_tokens
        )

        model = _normalise_model_name(response.model)
        return {
            "estimation": choice.message.content or "",
            "model": model,
            "provider": _provider_from_model(model),
            "finish_reason": finish_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            "latency_ms": latency_ms,
            "cost_usd": _estimate_cost(model, input_tokens, output_tokens),
        }
