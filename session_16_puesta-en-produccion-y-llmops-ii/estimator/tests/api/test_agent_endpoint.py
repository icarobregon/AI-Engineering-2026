"""Tests de ``POST /v1/estimate/agent/run`` (Sesión 12, expuesto en la S15).

Sin red: se sustituye ``run_estimation_agent`` por un doble que devuelve una
estimación y una traza canónicas, y se comprueba lo que de verdad es del router —
la resolución de ajustes por llamada, la validación y el mapeo de errores.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.routers.agent as agent_router
from app.generation.agentic.agent_schemas import AgentEstimate, AgentTrace
from app.main import app

pytestmark = pytest.mark.real_auth

KEY = "clave-de-servicio-para-tests"
AUTH = {"X-API-Key": KEY}
TRANSCRIPCION = "Necesitamos un backend de negocio, una integración con el ERP y una app móvil. " * 3


def _estimacion() -> AgentEstimate:
    return AgentEstimate(
        project="Plataforma logística",
        components=[],
        total_hours=320.0,
        notes="Sin precedentes para la app móvil.",
    )


@pytest.fixture
def client(monkeypatch) -> TestClient:
    import app.api.security as security

    ajustes = type(
        "S",
        (),
        {
            "ESTIMATE_API_KEY": KEY,
            "RETRIEVAL_API_KEY": KEY,
            "AGENT_MODEL": "gpt-5",
            "AGENT_REASONING_EFFORT": "medium",
            "AGENT_MAX_ITERATIONS": 10,
        },
    )()
    monkeypatch.setattr(security, "get_settings", lambda: ajustes)
    app.dependency_overrides[agent_router.get_settings] = lambda: ajustes
    monkeypatch.setattr(agent_router, "get_async_openai_client", lambda: object())
    monkeypatch.setattr(agent_router, "get_budget_search_backend", lambda: object())
    yield TestClient(app)
    app.dependency_overrides.clear()


def _capturar(monkeypatch) -> dict:
    """Sustituye el bucle y devuelve el dict donde aterrizan sus argumentos."""
    visto: dict = {}

    async def falso(transcript, *, client, backend, model, reasoning_effort, max_iterations):
        visto.update(
            model=model, reasoning_effort=reasoning_effort, max_iterations=max_iterations
        )
        return _estimacion(), AgentTrace(model=model, reasoning_effort=reasoning_effort)

    monkeypatch.setattr(agent_router, "run_estimation_agent", falso)
    return visto


def test_sin_ajustes_cae_a_los_del_entorno(client, monkeypatch) -> None:
    """Un perfil que sólo cambia el modelo no tiene que repetir lo demás."""
    visto = _capturar(monkeypatch)

    respuesta = client.post(
        "/v1/estimate/agent/run", json={"transcript": TRANSCRIPCION}, headers=AUTH
    )

    assert respuesta.status_code == 200
    assert visto == {"model": "gpt-5", "reasoning_effort": "medium", "max_iterations": 10}


def test_los_ajustes_de_la_llamada_mandan(client, monkeypatch) -> None:
    visto = _capturar(monkeypatch)

    respuesta = client.post(
        "/v1/estimate/agent/run",
        json={
            "transcript": TRANSCRIPCION,
            "model": "gpt-5-mini",
            "reasoning_effort": "low",
            "max_iterations": 4,
        },
        headers=AUTH,
    )

    assert respuesta.status_code == 200
    assert visto == {"model": "gpt-5-mini", "reasoning_effort": "low", "max_iterations": 4}
    assert respuesta.json()["estimate"]["total_hours"] == 320.0


def test_un_esfuerzo_imposible_es_422_no_un_fallo_del_proveedor(client, monkeypatch) -> None:
    """Se valida aquí para no descubrirlo a los tres minutos, dentro del bucle."""
    _capturar(monkeypatch)

    respuesta = client.post(
        "/v1/estimate/agent/run",
        json={"transcript": TRANSCRIPCION, "reasoning_effort": "turbo"},
        headers=AUTH,
    )

    assert respuesta.status_code == 422
    assert "reasoning_effort" in respuesta.json()["detail"]


def test_una_transcripcion_corta_no_llega_al_modelo(client, monkeypatch) -> None:
    _capturar(monkeypatch)

    respuesta = client.post(
        "/v1/estimate/agent/run", json={"transcript": "muy corta"}, headers=AUTH
    )

    assert respuesta.status_code == 422


def test_sin_clave_de_openai_responde_503(client, monkeypatch) -> None:
    """El agente no puede correr sin clave, y 503 es lo que dice «falta algo»."""
    _capturar(monkeypatch)
    monkeypatch.setattr(agent_router, "get_async_openai_client", lambda: None)

    respuesta = client.post(
        "/v1/estimate/agent/run", json={"transcript": TRANSCRIPCION}, headers=AUTH
    )

    assert respuesta.status_code == 503


def test_un_fallo_del_bucle_es_502(client, monkeypatch) -> None:
    async def revienta(*_a, **_k):
        raise RuntimeError("el proveedor cerró la conexión")

    monkeypatch.setattr(agent_router, "run_estimation_agent", revienta)

    respuesta = client.post(
        "/v1/estimate/agent/run", json={"transcript": TRANSCRIPCION}, headers=AUTH
    )

    assert respuesta.status_code == 502
    assert "el proveedor cerró la conexión" in respuesta.json()["detail"]
