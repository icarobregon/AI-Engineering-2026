"""Tests for application configuration."""

from app.config import Settings, settings


def test_settings_has_llm_provider():
    """Settings object exposes LLM_PROVIDER."""
    assert hasattr(settings, "LLM_PROVIDER")


def test_settings_default_provider():
    """Default LLM provider is openai."""
    assert settings.LLM_PROVIDER in ("openai", "anthropic")


def test_settings_ignores_extra_env_vars(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=development\n"
        "LLM_PROVIDER=openai\n"
        "LLM_MODEL=gpt-4o-mini\n"
        "BACKEND_URL=http://localhost:8000\n"
        "SOME_OTHER_VAR=foo\n"
    )
    s = Settings(_env_file=str(env_file))
    assert s.LLM_PROVIDER == "openai"
    assert not hasattr(s, "BACKEND_URL")
