"""Shared rate limiter.

Lives above the layers (next to ``config``/``dependencies``) because both the
routers and the app factory need the same instance: the routers to decorate
their endpoints, ``main`` to register the state and the 429 handler.

Keyed by **API key**, not by IP. Two clients behind the same corporate NAT are
two consumers with two quotas, and one misbehaving integration must not exhaust
the other's budget. The IP is only the fallback for unauthenticated requests,
which the guarded routers reject anyway.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette import status


def api_key_or_ip(request: Request) -> str:
    return request.headers.get("x-api-key") or get_remote_address(request)


limiter = Limiter(key_func=api_key_or_ip)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 that tells the caller what to do instead of just saying no."""
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "rate_limit_exceeded",
            "limit": str(exc.detail),
            "retry_after_seconds": 60,
        },
        headers={"Retry-After": "60"},
    )
