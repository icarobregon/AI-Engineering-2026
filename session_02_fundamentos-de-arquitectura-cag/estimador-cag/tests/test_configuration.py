"""Tests for application configuration."""

from app.config import settings


def test_settings_has_llm_provider():
    """Settings object exposes LLM_PROVIDER."""
    assert hasattr(settings, "LLM_PROVIDER")


def test_settings_default_provider():
    """Default LLM provider is openai."""
    assert settings.LLM_PROVIDER in ("openai", "anthropic")
