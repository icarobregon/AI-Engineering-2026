"""Las rutas que dejaron de ser anónimas en la Sesión 15.

Hasta este cambio, `/sessions/*`, `/embeddings/*`, `/api/v1/config/*`,
`POST /search` y `/api/v1/ingestion/*` contestaban sin cabecera. La frontera de
red seguía intacta —el servicio IA no publica puerto— pero dentro de la red
cualquiera podía conversar (y gastar tokens del proveedor), escribir en el corpus
o cambiar el modelo que atiende todo lo demás.

Estos tests van sobre la cerradura, así que llevan `real_auth`: el bypass del
conftest anularía justo lo que se quiere comprobar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.security as security
from app.main import app

pytestmark = pytest.mark.real_auth

KEY = "clave-de-servicio-para-tests"
AUTH = {"X-API-Key": KEY}


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # Las dos claves valen lo mismo aquí a propósito: lo que se prueba es que cada
    # ruta EXIGE una, no cuál de las dos. Que `/search` lleve la de retrieval y no
    # la de estimación se lee en `app/api/search.py`, no se adivina desde un test.
    ajustes = type("S", (), {"ESTIMATE_API_KEY": KEY, "RETRIEVAL_API_KEY": KEY})()
    monkeypatch.setattr(security, "get_settings", lambda: ajustes)
    return TestClient(app)


# Una por familia y por verbo: leer también estaba abierto, y `GET
# /api/v1/config/models` enumera la configuración efectiva del servicio.
CERRADAS = [
    ("POST", "/sessions"),
    ("GET", "/sessions/cualquiera"),
    ("POST", "/sessions/cualquiera/estimate"),
    ("POST", "/sessions/cualquiera/estimate-acb"),
    ("POST", "/embeddings/ingest"),
    ("POST", "/embeddings/compare"),
    ("GET", "/embeddings/index/stats"),
    ("GET", "/v1/estimate/graph/diagram"),
    ("GET", "/api/v1/config/models"),
    ("PUT", "/api/v1/config/models"),
    ("GET", "/api/v1/config/retrieval"),
    ("PUT", "/api/v1/config/retrieval"),
    # La de la S08, con la clave de retrieval: es la que usa su sustituta.
    ("POST", "/search"),
    # El pipeline offline: lanza corridas que ESCRIBEN en el corpus.
    ("POST", "/api/v1/ingestion/runs"),
    ("GET", "/api/v1/ingestion/jobs/cualquiera"),
]


@pytest.mark.parametrize(("metodo", "ruta"), CERRADAS)
def test_sin_cabecera_responde_401(client: TestClient, metodo: str, ruta: str) -> None:
    respuesta = client.request(metodo, ruta, json={})
    assert respuesta.status_code == 401
    # La cabecera del reto es parte del contrato: dice CÓMO autenticarse.
    assert respuesta.headers["WWW-Authenticate"] == "X-API-Key"


@pytest.mark.parametrize(("metodo", "ruta"), CERRADAS)
def test_con_clave_equivocada_responde_401(client: TestClient, metodo: str, ruta: str) -> None:
    respuesta = client.request(metodo, ruta, json={}, headers={"X-API-Key": "no-es"})
    assert respuesta.status_code == 401


@pytest.mark.parametrize(("metodo", "ruta"), CERRADAS)
def test_con_la_clave_pasa_del_guardia(client: TestClient, metodo: str, ruta: str) -> None:
    """Con la clave, el 401 desaparece.

    No se afirma 200: sin overrides de dependencias, varias de estas rutas fallan
    más abajo (404 de sesión inexistente, 422 de cuerpo vacío, 503 sin Redis). Lo
    que se comprueba es que el guardia ya no es quien rechaza.
    """
    respuesta = client.request(metodo, ruta, json={}, headers=AUTH)
    assert respuesta.status_code != 401


def test_health_sigue_abierto(client: TestClient) -> None:
    """El healthcheck de Docker no lleva cabecera: cerrarlo mataría el contenedor."""
    assert client.get("/health").status_code == 200
