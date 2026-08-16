"""Idempotency store for expensive, non-idempotent endpoints.

A ``from-transcript`` estimate is two LLM calls plus an embedding. A business
backend that retries on a socket timeout — which is the correct thing for it to
do — would pay for all of it twice and, worse, hand the user a second estimate
with different numbers for the same meeting. The key makes the retry return the
first answer instead.

Same Redis as the CAG caches but a separate namespace: this is not a cache and
must not be reasoned about as one. A cache miss is free; an idempotency miss
means double billing. Nothing here is ever evicted early on memory pressure
grounds — the TTL is the only expiry.
"""

from __future__ import annotations

import redis
import structlog

log = structlog.get_logger()

NAMESPACE = "idempotency:estimate"


class IdempotencyStore:
    """Key → serialized response, with a fixed TTL."""

    def __init__(self, redis_client: redis.Redis, ttl: int = 86_400) -> None:
        self.redis = redis_client
        self.ttl = ttl

    @classmethod
    def from_url(cls, url: str, ttl: int = 86_400) -> "IdempotencyStore":
        return cls(redis.from_url(url, decode_responses=True), ttl=ttl)

    @staticmethod
    def _key(idempotency_key: str) -> str:
        return f"{NAMESPACE}:{idempotency_key}"

    def get(self, idempotency_key: str) -> str | None:
        try:
            return self.redis.get(self._key(idempotency_key))
        except redis.RedisError as exc:  # Redis down must not break estimation.
            log.warning("idempotency_lookup_failed", error=str(exc)[:200])
            return None

    def set(self, idempotency_key: str, payload: str) -> None:
        try:
            self.redis.setex(self._key(idempotency_key), self.ttl, payload)
        except redis.RedisError as exc:
            log.warning("idempotency_store_failed", error=str(exc)[:200])
