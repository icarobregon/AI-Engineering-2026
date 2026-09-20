"""Tests de ``GET /embeddings/index/stats`` (la foto del corpus).

Sin Postgres: se sustituye la fábrica de sesiones por una falsa que responde a
las consultas que ``corpus_stats.collect`` hace, en el orden en que las hace. Lo
que se ejerce es el cableado del router y la forma de la respuesta, que es el
contrato que consume la pantalla «Corpus e índice».
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_corpus_session_factory
from app.main import app


class _Fila:
    """Resultado de un `execute`: sirve `.one()`, `.scalar_one()` o iteración."""

    def __init__(self, valor):
        self._valor = valor

    def one(self):
        return self._valor

    def scalar_one(self):
        return self._valor

    def __iter__(self):
        return iter(self._valor)


class _SesionFalsa:
    """Responde en el orden en que ``collect`` pregunta.

    1) las tablas con índice HNSW, 2) (chunks, documentos) por cada una de las
    tres colecciones, 3) el total de documentos.
    """

    def __init__(self, *, tablas_hnsw, por_coleccion, total_documentos):
        self._respuestas = [
            [(t,) for t in tablas_hnsw],
            *por_coleccion,
            total_documentos,
        ]
        self.consultas = 0

    async def execute(self, _consulta):
        valor = self._respuestas[self.consultas]
        self.consultas += 1
        return _Fila(valor)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def _fabrica(sesion):
    return lambda: sesion


@pytest.fixture(autouse=True)
def _limpiar():
    yield
    app.dependency_overrides.pop(get_corpus_session_factory, None)


def test_cuenta_por_coleccion_y_suma_el_total() -> None:
    sesion = _SesionFalsa(
        tablas_hnsw=["budget_chunks"],
        por_coleccion=[(1603, 77), (12, 3), (0, 0)],
        total_documentos=80,
    )
    app.dependency_overrides[get_corpus_session_factory] = lambda: _fabrica(sesion)

    respuesta = TestClient(app).get("/embeddings/index/stats")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [c["collection"] for c in cuerpo["collections"]] == [
        "budget",
        "transcript",
        "technical_doc",
    ]
    assert cuerpo["collections"][0] == {
        "collection": "budget",
        "documents": 77,
        "chunks": 1603,
        "hnsw_indexed": True,
    }
    # El total NO se pide a la base de datos: se suma de las colecciones, que es
    # la única forma de que no pueda contradecir a sus propias filas.
    assert cuerpo["total_chunks"] == 1603 + 12 + 0
    assert cuerpo["total_documents"] == 80


def test_una_coleccion_sin_indice_se_reporta_sin_indice() -> None:
    """El dato que no se adivina mirando las filas, y el que la pantalla resalta."""
    sesion = _SesionFalsa(
        tablas_hnsw=[],
        por_coleccion=[(1603, 77), (0, 0), (0, 0)],
        total_documentos=77,
    )
    app.dependency_overrides[get_corpus_session_factory] = lambda: _fabrica(sesion)

    cuerpo = TestClient(app).get("/embeddings/index/stats").json()

    assert all(c["hnsw_indexed"] is False for c in cuerpo["collections"])


def test_corpus_vacio_responde_ceros_no_error() -> None:
    """Un corpus recién creado es un estado normal, no un fallo."""
    sesion = _SesionFalsa(
        tablas_hnsw=[],
        por_coleccion=[(0, 0), (0, 0), (0, 0)],
        total_documentos=0,
    )
    app.dependency_overrides[get_corpus_session_factory] = lambda: _fabrica(sesion)

    respuesta = TestClient(app).get("/embeddings/index/stats")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total_chunks"] == 0
    assert len(cuerpo["collections"]) == 3


def test_postgres_caido_responde_503_no_500() -> None:
    """Una dependencia caída es 503, que el BFF sabe traducir; 500 no dice nada."""

    class _SesionQueRevienta:
        async def execute(self, _consulta):
            raise OSError("Connect call failed")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    app.dependency_overrides[get_corpus_session_factory] = lambda: (
        lambda: _SesionQueRevienta()
    )

    respuesta = TestClient(app).get("/embeddings/index/stats")

    assert respuesta.status_code == 503
    assert respuesta.json()["detail"] == "Corpus store unavailable"
