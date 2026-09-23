"""HTTP tests for GET/PUT /api/v1/config/models (runtime model settings)."""

from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_runtime_config
from app.foundation.llm.runtime_config import RuntimeModelConfig
from app.main import app


def make_settings(**overrides) -> Settings:
    defaults = {
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "TYPESAFE_API_KEY": "ts-test",
    }
    return Settings(_env_file=None, **{**defaults, **overrides})


@pytest.fixture
def fake_store():
    settings = make_settings()
    store = RuntimeModelConfig(fakeredis.FakeRedis(decode_responses=True), settings)
    app.dependency_overrides[get_runtime_config] = lambda: store
    app.dependency_overrides[get_settings] = lambda: settings
    yield store
    app.dependency_overrides.clear()


@pytest.fixture
def client(fake_store) -> TestClient:
    return TestClient(app)


def test_get_returns_full_snapshot(client) -> None:
    response = client.get("/api/v1/config/models")

    assert response.status_code == 200
    body = response.json()
    assert body["models"]["PRIMARY_MODEL"] == {
        "effective": "gpt-4o-mini",
        "default": "gpt-4o-mini",
        "overridden": False,
    }
    assert set(body["models"]) == {
        "PRIMARY_MODEL",
        "FALLBACK_MODEL",
        "CRITIC_MODEL",
        "METADATA_EXTRACTOR_MODEL",
        "COMPRESSION_MODEL",
        "PROPOSITIONAL_CHUNKER_MODEL",
        "CONTEXTUAL_CHUNKER_MODEL",
        "GRAPH_SUPERVISOR_MODEL",
    }
    assert "gpt-4o" in body["available_models"]
    assert "claude-sonnet-4-5" in body["available_models"]
    assert body["embedding_model"] == "text-embedding-3-small"


def test_available_models_filtered_by_configured_keys(fake_store) -> None:
    # No Anthropic key → claude models leave the catalog.
    settings = make_settings(ANTHROPIC_API_KEY=None)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)

    body = client.get("/api/v1/config/models").json()

    assert all(not model.startswith("claude") for model in body["available_models"])
    assert "gpt-4o-mini" in body["available_models"]


def test_put_overrides_and_returns_fresh_snapshot(client, fake_store) -> None:
    response = client.put("/api/v1/config/models", json={"models": {"PRIMARY_MODEL": "gpt-4o"}})

    assert response.status_code == 200
    body = response.json()
    assert body["models"]["PRIMARY_MODEL"] == {
        "effective": "gpt-4o",
        "default": "gpt-4o-mini",
        "overridden": True,
    }
    assert fake_store.effective("PRIMARY_MODEL") == "gpt-4o"


def test_put_null_resets_override(client, fake_store) -> None:
    fake_store.set("PRIMARY_MODEL", "gpt-4o")

    response = client.put("/api/v1/config/models", json={"models": {"PRIMARY_MODEL": None}})

    assert response.status_code == 200
    assert response.json()["models"]["PRIMARY_MODEL"]["overridden"] is False
    assert fake_store.get("PRIMARY_MODEL") is None


def test_put_unknown_key_is_422(client) -> None:
    response = client.put("/api/v1/config/models", json={"models": {"EMBEDDING_MODEL": "gpt-4o"}})
    assert response.status_code == 422
    assert "Unknown model key" in response.json()["detail"]


def test_put_model_outside_catalog_is_422(client) -> None:
    response = client.put(
        "/api/v1/config/models", json={"models": {"PRIMARY_MODEL": "gpt-99-ultra"}}
    )
    assert response.status_code == 422
    assert "not in the catalog" in response.json()["detail"]


def test_put_model_with_missing_provider_key_is_400(fake_store) -> None:
    settings = make_settings(ANTHROPIC_API_KEY=None)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)

    response = client.put(
        "/api/v1/config/models", json={"models": {"PRIMARY_MODEL": "claude-sonnet-4-5"}}
    )

    assert response.status_code == 400
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_put_is_all_or_nothing(client, fake_store) -> None:
    # One invalid entry → the valid one must NOT be applied either.
    response = client.put(
        "/api/v1/config/models",
        json={"models": {"PRIMARY_MODEL": "gpt-4o", "BOGUS_KEY": "gpt-4o"}},
    )

    assert response.status_code == 422
    assert fake_store.is_overridden("PRIMARY_MODEL") is False


# --- S15 PoC: un modelo de decisión sólo vale para el knob del supervisor -----


def test_a_decision_model_is_rejected_for_a_knob_that_needs_text(client) -> None:
    response = client.put("/api/v1/config/models", json={"models": {"PRIMARY_MODEL": "jev-latest"}})

    # 422 y no 400: lo ilegal es el emparejamiento, no que falte una clave. Con
    # la clave de TypeSafe puesta —que en estos tests lo está— seguiría siéndolo,
    # y un 400 mandaría al operador a configurar algo que ya tiene.
    assert response.status_code == 422
    assert "GRAPH_SUPERVISOR_MODEL" in response.json()["detail"]


def test_the_supervisor_knob_is_the_one_that_takes_it(client, fake_store) -> None:
    response = client.put(
        "/api/v1/config/models", json={"models": {"GRAPH_SUPERVISOR_MODEL": "jev-latest"}}
    )

    assert response.status_code == 200
    assert fake_store.effective("GRAPH_SUPERVISOR_MODEL") == "jev-latest"


def test_the_restriction_travels_to_the_client_as_data(client) -> None:
    # La pantalla filtra con esto en vez de reimplementar la regla, que es lo
    # que la mantiene sincronizada con el 422 de arriba.
    body = client.get("/api/v1/config/models").json()

    assert body["decision_only_knobs"] == ["GRAPH_SUPERVISOR_MODEL"]
    assert "jev-latest" in body["decision_models"]


def test_decision_models_leave_the_catalog_without_a_typesafe_key() -> None:
    settings = make_settings(TYPESAFE_API_KEY=None)
    store = RuntimeModelConfig(fakeredis.FakeRedis(decode_responses=True), settings)
    app.dependency_overrides[get_runtime_config] = lambda: store
    app.dependency_overrides[get_settings] = lambda: settings

    body = TestClient(app).get("/api/v1/config/models").json()
    app.dependency_overrides.clear()

    assert "jev-latest" not in body["available_models"]
    assert body["decision_models"] == []
