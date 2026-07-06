"""Unit tests for OpenAIEmbedder: batching, retry and error handling.

No network: a fake OpenAI client stands in for ``client.embeddings.create``.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.embedding_pipeline import embedder as embedder_module
from app.embedding_pipeline.embedder import (
    BATCH_SIZE,
    COST_PER_MILLION_TOKENS_USD,
    OpenAIEmbedder,
)
from app.embedding_pipeline.schemas import Chunk


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


class FakeEmbeddings:
    def __init__(self, *, dim: int = 4, fail_times: int = 0, total_tokens: int = 10) -> None:
        self.dim = dim
        self.fail_times = fail_times
        self.total_tokens = total_tokens
        self.calls: list[list[str]] = []

    def create(self, *, model: str, input: list[str]):  # noqa: A002 - matches SDK kwarg
        if self.fail_times > 0:
            self.fail_times -= 1
            raise _rate_limit_error()
        self.calls.append(input)
        data = [SimpleNamespace(embedding=[float(i)] * self.dim) for i in range(len(input))]
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=self.total_tokens))


class FakeClient:
    def __init__(self, **kwargs) -> None:
        self.embeddings = FakeEmbeddings(**kwargs)


def _chunks(n: int) -> list[Chunk]:
    return [
        Chunk(chunk_id=f"b::c{i}", text=f"text {i}", metadata={"i": i}, token_count=i + 1)
        for i in range(n)
    ]


def test_cost_constant_unchanged() -> None:
    # The exercise pins this reference price; guard against accidental edits.
    assert COST_PER_MILLION_TOKENS_USD == 0.02


def test_embed_one_returns_vector() -> None:
    embedder = OpenAIEmbedder(client=FakeClient(dim=3))
    assert embedder.embed_one("hello") == [0.0, 0.0, 0.0]


def test_embed_many_preserves_chunk_fields() -> None:
    embedder = OpenAIEmbedder(client=FakeClient(dim=2))
    chunks = _chunks(3)
    embedded = embedder.embed_many(chunks)
    assert len(embedded) == 3
    for original, result in zip(chunks, embedded):
        assert result.chunk_id == original.chunk_id
        assert result.text == original.text
        assert result.metadata == original.metadata
        assert result.token_count == original.token_count
        assert len(result.embedding) == 2


def test_embed_many_batches_by_100() -> None:
    client = FakeClient(dim=1)
    embedder = OpenAIEmbedder(client=client)
    embedded = embedder.embed_many(_chunks(250))
    assert len(embedded) == 250
    # 250 chunks -> 100 + 100 + 50.
    assert [len(c) for c in client.embeddings.calls] == [BATCH_SIZE, BATCH_SIZE, 50]


def test_retry_on_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    embedder = OpenAIEmbedder(client=FakeClient(dim=2, fail_times=2))
    result = embedder.embed_one("hello")
    assert len(result) == 2
    assert sleeps == [1, 2]  # exponential backoff on the two failed attempts


def test_retry_exhausted_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda s: None)
    # 4 failures > 3 retries -> the error propagates.
    embedder = OpenAIEmbedder(client=FakeClient(dim=2, fail_times=4))
    with pytest.raises(RateLimitError):
        embedder.embed_one("hello")


def test_missing_client_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedder_module, "get_openai_client", lambda: None)
    with pytest.raises(RuntimeError):
        OpenAIEmbedder()
