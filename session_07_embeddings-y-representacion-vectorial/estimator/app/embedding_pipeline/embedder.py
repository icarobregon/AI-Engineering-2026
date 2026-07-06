"""OpenAI embedder for the pipeline.

Wraps the shared ``get_openai_client()`` singleton and calls the Embeddings API
with ``text-embedding-3-small`` at its default dimension (1536; the Matryoshka
truncation discussion is left for the live session). Batches requests and retries
rate-limit errors with a simple exponential backoff.
"""

from __future__ import annotations

import time

import structlog
from openai import RateLimitError

from app.config import get_settings
from app.dependencies import get_openai_client
from app.embedding_pipeline.schemas import Chunk, EmbeddedChunk

log = structlog.get_logger()

# Reference price for text-embedding-3-small input tokens, May 2026. Subject to
# change — used only for the ballpark cost figure returned in the API stats.
COST_PER_MILLION_TOKENS_USD = 0.02

BATCH_SIZE = 100
_RETRY_BACKOFFS = (1, 2, 4)  # seconds; three retries on rate limit


class OpenAIEmbedder:
    def __init__(self, client=None, model: str | None = None) -> None:
        self._client = client if client is not None else get_openai_client()
        if self._client is None:
            raise RuntimeError("OpenAI client unavailable: OPENAI_API_KEY is not set.")
        self._model = model or get_settings().EMBEDDING_MODEL

    def embed_one(self, text: str) -> list[float]:
        response = self._create([text])
        return response.data[0].embedding

    def embed_many(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        embedded: list[EmbeddedChunk] = []
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            started = time.monotonic()
            response = self._create([c.text for c in batch])
            elapsed_ms = round((time.monotonic() - started) * 1000, 1)
            log.info(
                "embeddings_batch_processed",
                model=self._model,
                chunks=len(batch),
                total_tokens=response.usage.total_tokens,
                latency_ms=elapsed_ms,
            )
            for chunk, item in zip(batch, response.data):
                embedded.append(
                    EmbeddedChunk(**chunk.model_dump(), embedding=item.embedding)
                )
        return embedded

    def _create(self, inputs: list[str]):
        """Call the Embeddings API, retrying rate limits with backoff."""
        for attempt, backoff in enumerate((*_RETRY_BACKOFFS, None)):
            try:
                return self._client.embeddings.create(model=self._model, input=inputs)
            except RateLimitError:
                if backoff is None:
                    raise
                log.warning(
                    "embeddings_rate_limited",
                    attempt=attempt + 1,
                    backoff_s=backoff,
                )
                time.sleep(backoff)
        # Unreachable: the loop either returns or re-raises on the final attempt.
        raise RuntimeError("embeddings retry loop exhausted")
