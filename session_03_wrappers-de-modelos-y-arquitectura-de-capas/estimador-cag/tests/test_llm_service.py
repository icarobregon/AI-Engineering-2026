"""Tests for app/services/llm_service.py."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.context.examples import ESTIMATION_EXAMPLES
from app.services.llm_service import _build_system_prompt, generate_estimation, stream_estimation


# ---------------------------------------------------------------------------
# _build_system_prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_returns_non_empty_string():
    prompt = _build_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_build_system_prompt_contains_role_instructions():
    prompt = _build_system_prompt()
    assert "senior software consultant" in prompt.lower() or "project estimation" in prompt.lower()


def test_build_system_prompt_contains_example_content():
    prompt = _build_system_prompt()
    first_example = ESTIMATION_EXAMPLES[0]
    assert first_example["meeting_summary"][:50] in prompt


def test_build_system_prompt_contains_all_example_markers():
    prompt = _build_system_prompt()
    for i in range(1, len(ESTIMATION_EXAMPLES) + 1):
        assert f"--- EXAMPLE {i} ---" in prompt


# ---------------------------------------------------------------------------
# Helpers para construir respuestas falsas de cada proveedor
# ---------------------------------------------------------------------------


def _make_openai_response(content: str = "Estimación de prueba"):
    """Objeto mínimo que imita openai.ChatCompletion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50, total_tokens=150),
    )


def _make_anthropic_response(text: str = "Estimación Anthropic"):
    """Objeto mínimo que imita anthropic.Message response."""
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=60),
    )


# ---------------------------------------------------------------------------
# generate_estimation — rama OpenAI
#
# openai/anthropic se importan de forma lazy dentro del cuerpo de la función,
# por lo que no son atributos del módulo llm_service. Hay que parchear
# directamente openai.OpenAI y anthropic.Anthropic en su propio paquete.
# ---------------------------------------------------------------------------


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_generate_estimation_openai_returns_correct_keys(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _make_openai_response("Estimación OpenAI")

    result = generate_estimation("El cliente necesita una web corporativa.")

    assert "estimation" in result
    assert "model" in result
    assert "provider" in result


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_generate_estimation_openai_returns_correct_values(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _make_openai_response("Estimación OpenAI")

    result = generate_estimation("El cliente necesita una web corporativa.")

    assert result["estimation"] == "Estimación OpenAI"
    assert result["model"] == "gpt-4o-mini"
    assert result["provider"] == "openai"


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_generate_estimation_openai_sends_system_and_user_messages(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = _make_openai_response()

    transcription = "El cliente quiere un e-commerce con pasarela de pago."
    generate_estimation(transcription)

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]
    roles = [m["role"] for m in messages]

    assert "system" in roles
    assert "user" in roles
    user_message = next(m for m in messages if m["role"] == "user")
    assert user_message["content"] == transcription


# ---------------------------------------------------------------------------
# generate_estimation — rama Anthropic
# ---------------------------------------------------------------------------


@patch("app.services.llm_service.settings")
@patch("anthropic.Anthropic")
def test_generate_estimation_anthropic_returns_correct_values(mock_anthropic_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "anthropic"
    mock_settings.LLM_MODEL = "claude-haiku-4-5"
    mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"

    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_anthropic_response("Estimación Anthropic")

    result = generate_estimation("El cliente necesita una app móvil.")

    assert result["estimation"] == "Estimación Anthropic"
    assert result["model"] == "claude-haiku-4-5"
    assert result["provider"] == "anthropic"


@patch("app.services.llm_service.settings")
@patch("anthropic.Anthropic")
def test_generate_estimation_anthropic_sends_correct_arguments(mock_anthropic_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "anthropic"
    mock_settings.LLM_MODEL = "claude-haiku-4-5"
    mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"

    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.return_value = _make_anthropic_response()

    transcription = "El cliente quiere un dashboard de métricas."
    generate_estimation(transcription)

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"
    assert call_kwargs["messages"][0]["role"] == "user"
    assert call_kwargs["messages"][0]["content"] == transcription
    assert "system" in call_kwargs


# ---------------------------------------------------------------------------
# generate_estimation — propagación de errores
# ---------------------------------------------------------------------------


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_generate_estimation_propagates_openai_error(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("API connection error")

    with pytest.raises(Exception, match="API connection error"):
        generate_estimation("Transcripción de prueba para error.")


@patch("app.services.llm_service.settings")
@patch("anthropic.Anthropic")
def test_generate_estimation_propagates_anthropic_error(mock_anthropic_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "anthropic"
    mock_settings.LLM_MODEL = "claude-haiku-4-5"
    mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"

    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.create.side_effect = Exception("Anthropic rate limit")

    with pytest.raises(Exception, match="Anthropic rate limit"):
        generate_estimation("Transcripción de prueba para error.")


# ---------------------------------------------------------------------------
# stream_estimation — OpenAI branch
# ---------------------------------------------------------------------------


def _make_openai_chunk(content: str = "", finish_reason=None, usage=None):
    choice = SimpleNamespace(
        delta=SimpleNamespace(content=content if content else None),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_openai_usage_chunk(prompt_tokens=100, completion_tokens=50):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(choices=[], usage=usage)


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_stream_estimation_openai_yields_deltas_then_meta(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    chunks = [
        _make_openai_chunk("Hola "),
        _make_openai_chunk("mundo"),
        _make_openai_chunk(finish_reason="stop"),
        _make_openai_usage_chunk(prompt_tokens=123, completion_tokens=45),
    ]
    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.return_value = iter(chunks)

    events = list(stream_estimation("Cliente quiere una landing."))

    assert events[0] == {"type": "delta", "text": "Hola "}
    assert events[1] == {"type": "delta", "text": "mundo"}
    meta = events[-1]
    latency_ms = meta.pop("latency_ms")
    assert isinstance(latency_ms, float)
    assert latency_ms >= 0
    assert meta == {
        "type": "meta",
        "model": "gpt-4o-mini",
        "provider": "openai",
        "tokens_in": 123,
        "tokens_out": 45,
        "finish_reason": "stop",
    }


@patch("app.services.llm_service.settings")
@patch("openai.OpenAI")
def test_stream_estimation_openai_error_yields_error_event(mock_openai_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "openai"
    mock_settings.LLM_MODEL = "gpt-4o-mini"
    mock_settings.OPENAI_API_KEY = "sk-test"

    mock_client = MagicMock()
    mock_openai_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = RuntimeError("LLM down")

    events = list(stream_estimation("Transcripción para forzar error."))

    assert events == [{"type": "error", "message": "LLM down"}]


# ---------------------------------------------------------------------------
# stream_estimation — Anthropic branch
# ---------------------------------------------------------------------------


class _FakeAnthropicStream:
    def __init__(self, chunks, final_message):
        self.text_stream = iter(chunks)
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_final_message(self):
        return self._final


@patch("app.services.llm_service.settings")
@patch("anthropic.Anthropic")
def test_stream_estimation_anthropic_yields_deltas_then_meta(mock_anthropic_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "anthropic"
    mock_settings.LLM_MODEL = "claude-haiku-4-5"
    mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"

    final_message = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=200, output_tokens=80),
        stop_reason="end_turn",
    )
    fake_stream = _FakeAnthropicStream(["Hola ", "mundo"], final_message)

    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.stream.return_value = fake_stream

    events = list(stream_estimation("Cliente quiere un dashboard."))

    assert events[0] == {"type": "delta", "text": "Hola "}
    assert events[1] == {"type": "delta", "text": "mundo"}
    meta = events[-1]
    latency_ms = meta.pop("latency_ms")
    assert isinstance(latency_ms, float)
    assert latency_ms >= 0
    assert meta == {
        "type": "meta",
        "model": "claude-haiku-4-5",
        "provider": "anthropic",
        "tokens_in": 200,
        "tokens_out": 80,
        "finish_reason": "end_turn",
    }


@patch("app.services.llm_service.settings")
@patch("anthropic.Anthropic")
def test_stream_estimation_anthropic_error_yields_error_event(mock_anthropic_cls, mock_settings):
    mock_settings.LLM_PROVIDER = "anthropic"
    mock_settings.LLM_MODEL = "claude-haiku-4-5"
    mock_settings.ANTHROPIC_API_KEY = "sk-ant-test"

    mock_client = MagicMock()
    mock_anthropic_cls.return_value = mock_client
    mock_client.messages.stream.side_effect = RuntimeError("Anthropic timeout")

    events = list(stream_estimation("Transcripción para forzar error."))

    assert events == [{"type": "error", "message": "Anthropic timeout"}]
