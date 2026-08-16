"""API-key authentication for the Session 9 routers.

Two keys, not one, because the two surfaces have different blast radii. The
retrieval endpoint returns raw chunks of historical budgets: whoever holds that
key can walk the entire corpus a page at a time. The estimate endpoint costs
money per call but leaks the corpus only in digested form. Separate keys mean
either can be revoked or rotated without taking the other down — the exact
drill the "leaked key" scenario of the live session exercises.

``secrets.compare_digest`` rather than ``==`` because string equality in Python
short-circuits on the first differing byte. The timing difference is tiny but
measurable over many requests, and it leaks the key prefix byte by byte: an
attacker who can time responses recovers a 64-char key in ~64×256 requests
instead of 256^64. The comparison here always runs to the end.

An unset key means the router is unconfigured, not open: it answers 503. The
alternative in the session material (``os.environ[...]`` at import time) makes
the whole application unbootable without secrets, which breaks tests and local
development for a guarantee this already provides.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


def _check(provided: str, configured: str | None, surface: str) -> str:
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{surface} API key is not configured on the server.",
        )
    if not secrets.compare_digest(provided, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return provided


def require_retrieval_key(x_api_key: str = Header(...)) -> str:
    """Guard for ``/v1/retrieval/*``."""
    return _check(x_api_key, get_settings().RETRIEVAL_API_KEY, "Retrieval")


def require_estimate_key(x_api_key: str = Header(...)) -> str:
    """Guard for ``/v1/estimate/*``."""
    return _check(x_api_key, get_settings().ESTIMATE_API_KEY, "Estimate")
