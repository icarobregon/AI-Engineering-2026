"""Unit tests for app/dependencies.py.

All factory functions use @lru_cache, so each test clears the cache before and
after the call to prevent cross-test pollution.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# get_openai_client
# ---------------------------------------------------------------------------


def test_get_openai_client_returns_none_without_api_key() -> None:
    from app.dependencies import get_openai_client

    get_openai_client.cache_clear()
    try:
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = ""
            result = get_openai_client()
    finally:
        get_openai_client.cache_clear()

    assert result is None


def test_get_openai_client_returns_openai_instance_with_api_key() -> None:
    from openai import OpenAI

    from app.dependencies import get_openai_client

    get_openai_client.cache_clear()
    try:
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.OPENAI_API_KEY = "sk-fake-key-for-testing"
            result = get_openai_client()
    finally:
        get_openai_client.cache_clear()

    assert isinstance(result, OpenAI)


# ---------------------------------------------------------------------------
# get_semantic_cache
# ---------------------------------------------------------------------------


def test_get_semantic_cache_returns_none_when_no_openai_key() -> None:
    from app.dependencies import get_semantic_cache

    get_semantic_cache.cache_clear()
    try:
        with patch("app.dependencies.get_openai_client", return_value=None):
            result = get_semantic_cache()
    finally:
        get_semantic_cache.cache_clear()

    assert result is None


def test_get_semantic_cache_returns_none_when_setup_fails() -> None:
    from app.dependencies import get_semantic_cache

    get_semantic_cache.cache_clear()
    try:
        with patch("app.dependencies.get_openai_client", return_value=MagicMock()), \
             patch("app.dependencies.get_settings") as mock_settings, \
             patch("app.dependencies.EstimationSemanticCache", side_effect=RuntimeError("redisvl down")):
            mock_settings.return_value.OPENAI_API_KEY = "sk-fake"
            mock_settings.return_value.EMBEDDING_MODEL = "text-embedding-3-small"
            mock_settings.return_value.REDIS_URL = "redis://localhost:6379"
            mock_settings.return_value.SEMANTIC_CACHE_THRESHOLD = 0.92
            mock_settings.return_value.SEMANTIC_CACHE_TTL = 86400
            mock_settings.return_value.SEMANTIC_CACHE_LOG_ONLY = False
            result = get_semantic_cache()
    finally:
        get_semantic_cache.cache_clear()

    assert result is None


# ---------------------------------------------------------------------------
# get_session_store
# ---------------------------------------------------------------------------


def test_get_session_store_uses_configured_max_turns() -> None:
    from app.dependencies import get_session_store
    from app.sessions.store import SessionStore

    get_session_store.cache_clear()
    try:
        with patch("app.dependencies.get_settings") as mock_settings:
            mock_settings.return_value.MAX_CONVERSATION_TURNS = 12
            result = get_session_store()
    finally:
        get_session_store.cache_clear()

    assert isinstance(result, SessionStore)
    assert result._max_turns == 12
