"""Application configuration loaded from environment variables."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from .env file."""

    APP_ENV: Literal["local", "development", "staging", "production"] = "local"
    LOG_LEVEL: Literal["notset", "debug", "info", "warning", "warn", "error", "exception", "critical"] = "debug"
    LLM_PROVIDER: Literal["openai", "anthropic"] = "openai"
    LLM_MODEL: Literal["gpt-4o-mini", "claude-haiku-4-5"] = "gpt-4o-mini"
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
