"""HTTP layer for the runtime model configuration (Settings UI).

Thin router: validation of the partial update is the only logic here — the
override store lives in ``app/foundation/llm/runtime_config.py``. Changing a
model takes effect on the NEXT LLM call (wrapper/service read the store per
call); nothing is rebuilt and no restart is needed.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.security import require_estimate_key
from app.config import Settings, get_settings
from app.dependencies import get_runtime_config, get_runtime_retrieval_config
from app.foundation.llm.runtime_config import (
    MODEL_KEYS,
    QUERY_TRANSFORM_KEY,
    ROUTING_KEY,
    TEMPORAL_DECAY_KEY,
    RuntimeConfigUnavailable,
    RuntimeModelConfig,
    RuntimeRetrievalConfig,
)
from app.foundation.llm.typesafe import is_decision_model
from app.foundation.llm.wrapper import MODEL_COSTS, _provider_from_model

log = structlog.get_logger()

# Maps the PUT request field → the Redis hash key for the Session 10 stage toggles.
_STAGE_TOGGLE_KEYS = {
    "routing_enabled": ROUTING_KEY,
    "query_transform_enabled": QUERY_TRANSFORM_KEY,
    "temporal_decay_enabled": TEMPORAL_DECAY_KEY,
}

# Cerrada desde la S15-bis. Es la superficie mas poderosa del servicio: quien
# puede escribir aqui elige que modelo atiende TODO lo demas, y el catalogo va de
# 0,05 a 600 US$ por millon de tokens. El GET tambien, porque enumera la
# configuracion efectiva.
router = APIRouter(
    prefix="/api/v1/config",
    tags=["config"],
    dependencies=[Depends(require_estimate_key)],
)

EMBEDDING_MODEL_NOTE = "Read-only: changing it would invalidate all stored vectors."

PROVIDER_KEY_FIELDS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "typesafe": "TYPESAFE_API_KEY",
}


class ModelUpdateRequest(BaseModel):
    """Partial update: only the keys present are touched; ``null`` resets."""

    models: dict[str, str | None] = Field(min_length=1)


def _available_models(settings: Settings) -> list[str]:
    """The catalog, filtered by the API keys actually configured."""
    available = []
    for model in settings.AVAILABLE_MODELS:
        key_field = PROVIDER_KEY_FIELDS.get(_provider_from_model(model))
        if key_field and getattr(settings, key_field):
            available.append(model)
    return available


def _config_payload(runtime_config: RuntimeModelConfig, settings: Settings) -> dict:
    return {
        "models": runtime_config.snapshot(),
        "available_models": _available_models(settings),
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_model_note": EMBEDDING_MODEL_NOTE,
        # The catalogue is hand-curated, so it carries its own provenance: when
        # it was built and from whose model lists. Nothing refreshes it — a new
        # provider key or a new model release leaves it stale and silent, and
        # the only defence against that is saying the date out loud.
        "catalog_generated_at": settings.MODEL_CATALOG_GENERATED_AT,
        "catalog_sources": settings.MODEL_CATALOG_SOURCES,
        # USD per million tokens, so the picker can show what a knob costs. The
        # catalogue spans three orders of magnitude and several knobs run on
        # every turn: a price-blind dropdown invites picking the 150 USD model
        # for the summariser.
        "model_prices": {
            model: MODEL_COSTS[model]
            for model in _available_models(settings)
            if model in MODEL_COSTS
        },
        # La restricción por knob viaja como DATO, no duplicada en el cliente.
        # `available_models` sigue siendo una lista plana porque casi todo el
        # catálogo sirve para casi todo; lo que hay que decir es la excepción, y
        # decirla aquí es lo que evita que la pantalla se invente la regla y se
        # desincronice del 422 que la aplica de verdad.
        "decision_only_knobs": settings.DECISION_ONLY_KNOBS,
        "decision_models": [m for m in _available_models(settings) if is_decision_model(m)],
    }


@router.get("/models")
def get_models(
    runtime_config: RuntimeModelConfig = Depends(get_runtime_config),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Current model configuration: effective/default/overridden per knob."""
    return _config_payload(runtime_config, settings)


class RetrievalUpdateRequest(BaseModel):
    """Partial update of the Session 10 retrieval toggles. Only the keys present
    are touched; ``null`` resets a knob back to its .env default."""

    search_mode: str | None = Field(default=None, description="'vector' or 'hybrid'.")
    rerank: bool | None = Field(default=None, description="Enable cross-encoder reranking.")
    # Session 10 live: advanced-pipeline stage toggles.
    routing_enabled: bool | None = Field(default=None, description="Enable multi-index routing.")
    query_transform_enabled: bool | None = Field(
        default=None, description="Enable query expansion/decomposition."
    )
    temporal_decay_enabled: bool | None = Field(
        default=None, description="Enable temporal decay re-weighting."
    )
    # Session 10 live: per-task hours estimation knobs (numeric).
    task_hours_top_k: int | None = Field(
        default=None, ge=1, le=30, description="Neighbours per task for the hours consensus."
    )
    task_hours_distance_threshold: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Red-flag floor: no match beyond this distance."
    )


@router.get("/retrieval")
def get_retrieval(
    runtime_retrieval: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Current retrieval configuration: effective/default/overridden per toggle."""
    return {
        "retrieval": runtime_retrieval.snapshot(),
        "reranker_model": settings.RERANKER_MODEL,
    }


@router.put("/retrieval")
def update_retrieval(
    request: RetrievalUpdateRequest,
    runtime_retrieval: RuntimeRetrievalConfig = Depends(get_runtime_retrieval_config),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Flip search mode and/or reranking at runtime — effective on the next
    retrieval, no restart. ``model_fields_set`` distinguishes "reset to default"
    (explicit ``null``) from "leave untouched" (key absent)."""
    sent = request.model_fields_set
    try:
        if "search_mode" in sent:
            try:
                runtime_retrieval.set_search_mode(request.search_mode)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            log.info("runtime_retrieval_changed", key="search_mode", new_value=request.search_mode)
        if "rerank" in sent:
            runtime_retrieval.set_rerank(request.rerank)
            log.info("runtime_retrieval_changed", key="rerank", new_value=request.rerank)
        for field_name, hash_key in _STAGE_TOGGLE_KEYS.items():
            if field_name in sent:
                runtime_retrieval.set_bool(hash_key, getattr(request, field_name))
                log.info(
                    "runtime_retrieval_changed",
                    key=field_name,
                    new_value=getattr(request, field_name),
                )
        if "task_hours_top_k" in sent:
            try:
                runtime_retrieval.set_task_hours_top_k(request.task_hours_top_k)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            log.info(
                "runtime_retrieval_changed",
                key="task_hours_top_k",
                new_value=request.task_hours_top_k,
            )
        if "task_hours_distance_threshold" in sent:
            try:
                runtime_retrieval.set_task_hours_distance_threshold(
                    request.task_hours_distance_threshold
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            log.info(
                "runtime_retrieval_changed",
                key="task_hours_distance_threshold",
                new_value=request.task_hours_distance_threshold,
            )
    except RuntimeConfigUnavailable as exc:
        log.error("runtime_retrieval_write_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Runtime config store unavailable") from exc

    return {
        "retrieval": runtime_retrieval.snapshot(),
        "reranker_model": settings.RERANKER_MODEL,
    }


@router.put("/models")
def update_models(
    request: ModelUpdateRequest,
    runtime_config: RuntimeModelConfig = Depends(get_runtime_config),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Apply a partial override update. All-or-nothing: every key/value in the
    payload is validated BEFORE anything is written."""
    available = _available_models(settings)

    # Validate everything first — a bad entry must not half-apply the batch.
    for key, value in request.models.items():
        if key not in MODEL_KEYS:
            raise HTTPException(status_code=422, detail=f"Unknown model key: {key}")
        if value is None:
            continue  # reset is always valid
        if value not in settings.AVAILABLE_MODELS:
            raise HTTPException(status_code=422, detail=f"Model '{value}' is not in the catalog")
        if is_decision_model(value) and key not in settings.DECISION_ONLY_KNOBS:
            # Antes que el check de clave, y no despues, a proposito: puesto
            # despues, un jev-* en PRIMARY_MODEL sin clave de TypeSafe contesta
            # "requires TYPESAFE_API_KEY, which is not configured" — le dice al
            # operador que configure una clave cuando lo que no es legal es el
            # emparejamiento, y con la clave puesta seguiria sin serlo.
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Model '{value}' only returns a decision, not text: it is valid for "
                    f"{', '.join(settings.DECISION_ONLY_KNOBS)}, not for '{key}'"
                ),
            )
        if value not in available:
            key_field = PROVIDER_KEY_FIELDS.get(_provider_from_model(value), "API key")
            raise HTTPException(
                status_code=400,
                detail=f"Model '{value}' requires {key_field}, which is not configured",
            )

    try:
        for key, value in request.models.items():
            old_effective = runtime_config.effective(key)
            runtime_config.set(key, value)
            log.info(
                "runtime_config_changed",
                key=key,
                old_effective=old_effective,
                new_value=value,
                reset=value is None,
            )
    except RuntimeConfigUnavailable as exc:
        log.error("runtime_config_write_failed", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Runtime config store unavailable") from exc

    return _config_payload(runtime_config, settings)
