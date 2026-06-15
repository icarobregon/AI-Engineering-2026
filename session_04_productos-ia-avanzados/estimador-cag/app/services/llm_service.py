"""LLM service: renders the versioned prompt and calls the configured provider."""

from app.config import settings
from app.logging import get_logger
from app.prompts.loader import render_estimation_prompt
from app.schemas.estimation import EstimationRequest

log = get_logger(__name__)


def generate_estimation(request: EstimationRequest, prompt_version: str = "v1") -> dict:
    """Generate a project estimation from a typed EstimationRequest.

    Returns:
        dict with keys: estimation (str), model (str), provider (str), prompt_version (str).
    """
    log.info(
        "llm_call_started",
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        project_type=request.project_type.value,
        detail_level=request.detail_level.value,
        output_format=request.output_format.value,
        description_length=len(request.description),
        prompt_version=prompt_version,
    )

    system_prompt, user_prompt = render_estimation_prompt(request, version=prompt_version)

    try:
        if settings.LLM_PROVIDER == "anthropic":
            import anthropic

            log.debug("using_anthropic_client")
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            response = client.messages.create(
                model=settings.LLM_MODEL,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
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
                    {"role": "user", "content": user_prompt},
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
            prompt_version=prompt_version,
        )

        return {
            "estimation": estimation_text,
            "model": settings.LLM_MODEL,
            "provider": settings.LLM_PROVIDER,
            "prompt_version": prompt_version,
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
