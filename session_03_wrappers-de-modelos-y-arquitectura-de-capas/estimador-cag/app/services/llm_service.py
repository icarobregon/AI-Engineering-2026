"""LLM service implementing the CAG (Cache Augmented Generation) pattern."""

import time
from typing import Iterator

from app.config import settings
from app.context.examples import ESTIMATION_EXAMPLES, format_examples_for_prompt
from app.logging import get_logger

log = get_logger(__name__)

SYSTEM_PROMPT_TEMPLATE = """\
You are a senior software consultant with 15+ years of experience in project estimation. Your task is to produce a detailed software project estimation based on a meeting transcription provided by the user.\n\n
Below are reference estimations from previous projects. Use them as a guide for structure, level of detail, and realistic pricing. Adapt the content to match the specific project described in the transcription.\n\n
Your output MUST follow this exact format:\n
- Project title as an H2 heading\n
- A task breakdown table with columns: Task, Hours, Cost (EUR)\n
- Total hours\n
- Total cost in EUR\n
- Recommended team composition\n
- Estimated duration in weeks\n\n
Use a developer rate of approximately 62.50 EUR/hour (500 EUR/day) and a designer rate of approximately 50 EUR/hour (400 EUR/day). Provide realistic, well-justified numbers.\n\n
{examples}
"""


def _build_system_prompt() -> str:
    """Build the system prompt with injected estimation examples."""
    examples_text = format_examples_for_prompt(ESTIMATION_EXAMPLES)
    prompt = SYSTEM_PROMPT_TEMPLATE.format(examples=examples_text)
    log.debug(
        "system_prompt_built",
        num_examples=len(ESTIMATION_EXAMPLES),
        prompt_length=len(prompt),
    )
    return prompt


def generate_estimation(transcription: str) -> dict:
    """Generate a project estimation from a meeting transcription.

    Uses the CAG pattern: injects cached estimation examples into the system
    prompt to calibrate the model's output without fine-tuning.

    Args:
        transcription: Raw text of the client meeting transcription.

    Returns:
        dict with keys: estimation (str), model (str), provider (str).
    """
    log.info(
        "llm_call_started",
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        transcription_length=len(transcription),
    )

    system_prompt = _build_system_prompt()

    try:
        if settings.LLM_PROVIDER == "anthropic":
            import anthropic

            log.debug("using_anthropic_client")
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": transcription}],
            )
            estimation_text = response.content[0].text
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            log.debug("anthropic_response_received")
        else:
            import openai

            log.debug("using_openai_client")
            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcription},
                ],
            )
            estimation_text = response.choices[0].message.content
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            log.debug("openai_response_received")

        log.info(
            "llm_call_completed",
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimation_length=len(estimation_text),
        )

        return {
            "estimation": estimation_text,
            "model": settings.LLM_MODEL,
            "provider": settings.LLM_PROVIDER,
        }

    except Exception as e:
        log.error(
            "llm_call_failed",
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
            error=str(e),
            exc_info=True,
        )
        raise


def stream_estimation(transcription: str) -> Iterator[dict]:
    """Stream a project estimation token-by-token from a meeting transcription.

    Yields dicts with a "type" key:
      - {"type": "delta", "text": str}                  — each text chunk
      - {"type": "meta", "model", "provider",
         "tokens_in", "tokens_out", "finish_reason"}    — once, when stream closes
      - {"type": "error", "message": str}               — if generation fails midway
    """
    log.info(
        "llm_stream_started",
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        transcription_length=len(transcription),
    )
    system_prompt = _build_system_prompt()
    start = time.perf_counter()
    tokens_in = tokens_out = 0
    finish_reason: str | None = None

    try:
        if settings.LLM_PROVIDER == "anthropic":
            import anthropic

            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            with client.messages.stream(
                model=settings.LLM_MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": transcription}],
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield {"type": "delta", "text": text}
                final_message = stream.get_final_message()
            tokens_in = final_message.usage.input_tokens
            tokens_out = final_message.usage.output_tokens
            finish_reason = final_message.stop_reason
        else:
            import openai

            client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
            stream = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcription},
                ],
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield {"type": "delta", "text": delta}
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
                if chunk.usage:
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens

        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        log.info(
            "llm_stream_completed",
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
        )
        yield {
            "type": "meta",
            "model": settings.LLM_MODEL,
            "provider": settings.LLM_PROVIDER,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "finish_reason": finish_reason,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        latency_ms = round((time.perf_counter() - start) * 1000, 1)
        log.error(
            "llm_stream_failed",
            provider=settings.LLM_PROVIDER,
            model=settings.LLM_MODEL,
            error_type=type(e).__name__,
            error_msg=str(e),
            latency_ms=latency_ms,
        )
        yield {"type": "error", "message": str(e)}
