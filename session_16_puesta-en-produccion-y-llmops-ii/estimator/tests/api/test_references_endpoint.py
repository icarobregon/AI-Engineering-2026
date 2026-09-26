"""``POST /v1/corpus/references`` — el contrato que ve el backend de negocio.

Lo que se fija aquí es lo que la pantalla necesita poder confiar: que el orden en
el que se preguntan las referencias es el orden en el que vuelven —quien pregunta
las tiene ordenadas por distancia y ese orden es información—, y que una
referencia que el corpus ya no tiene sale en ``missing`` en vez de desaparecer.
Ese caso no es teórico: el corpus se reindexa, y una estimación guardada cita
referencias de la indexación anterior.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routers import references as router_module
from app.dependencies import get_corpus_session_factory
from app.generation.rag.store.references import Reference, ReferenceTask
from app.main import app

AUTH = "TASK-2022-0032/Authentication & Access"
FRONT = "TASK-2024-0007/Frontend / UX"

REFERENCIA = Reference(
    reference_budget_id=AUTH,
    budget_id="TASK-2022-0032",
    module="Authentication & Access",
    project="Finance platform covering payments & billing",
    client_sector="finance",
    year=2022,
    main_technology="ruby_on_rails",
    total_hours=79.0,
    tasks=(
        ReferenceTask(
            component_id="AUTH-001",
            name="Role-based access control",
            description="Roles, permissions and policy checks across the API.",
            tech_stack="postgresql",
            complexity="medium",
            estimated_hours=16.0,
        ),
        ReferenceTask(
            component_id="AUTH-003",
            name="OAuth2 / OIDC login",
            description="Authorization-code flow with refresh tokens.",
            tech_stack="redis, postgresql, python",
            complexity="high",
            estimated_hours=63.0,
        ),
    ),
)


@pytest.fixture
def corpus(monkeypatch):
    """Sustituye la resolución, no la base: aquí se prueba la ruta, no el SQL."""
    resueltas: dict[str, Reference] = {}
    pedidas: list[list[str]] = []

    async def fake_resolve(_session, reference_budget_ids):
        pedidas.append(list(reference_budget_ids))
        return {k: v for k, v in resueltas.items() if k in reference_budget_ids}

    monkeypatch.setattr(router_module.store, "resolve", fake_resolve)

    class _Sesion:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return False

    app.dependency_overrides[get_corpus_session_factory] = lambda: _Sesion
    yield resueltas, pedidas
    app.dependency_overrides.pop(get_corpus_session_factory, None)


def test_devuelve_el_desglose_con_su_suma(corpus):
    resueltas, _ = corpus
    resueltas[AUTH] = REFERENCIA

    respuesta = TestClient(app).post("/v1/corpus/references", json={"references": [AUTH]})

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["missing"] == []
    (referencia,) = cuerpo["references"]
    assert referencia["module"] == "Authentication & Access"
    assert referencia["year"] == 2022
    assert referencia["main_technology"] == "ruby_on_rails"
    # El total es la suma del desglose que viaja debajo: es lo que hace que la
    # pantalla pueda decir «de aquí salen las 79 h» sin que sea una promesa.
    assert referencia["total_hours"] == 79.0
    assert sum(t["estimated_hours"] for t in referencia["tasks"]) == 79.0
    assert [t["name"] for t in referencia["tasks"]] == [
        "Role-based access control",
        "OAuth2 / OIDC login",
    ]


def test_conserva_el_orden_en_el_que_se_preguntan(corpus):
    # Llegan ordenadas por distancia; devolverlas en el orden del diccionario
    # perdería esa ordenación sin que se notara en pantalla.
    resueltas, _ = corpus
    otra = Reference(**{**REFERENCIA.__dict__, "reference_budget_id": FRONT, "module": "Frontend / UX"})
    resueltas[AUTH] = REFERENCIA
    resueltas[FRONT] = otra

    respuesta = TestClient(app).post(
        "/v1/corpus/references", json={"references": [FRONT, AUTH]}
    )

    assert [r["reference_budget_id"] for r in respuesta.json()["references"]] == [FRONT, AUTH]


def test_una_referencia_que_el_corpus_ya_no_tiene_sale_en_missing(corpus):
    resueltas, _ = corpus
    resueltas[AUTH] = REFERENCIA

    respuesta = TestClient(app).post(
        "/v1/corpus/references", json={"references": [AUTH, "TASK-1999-0001/Fantasma"]}
    )

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [r["reference_budget_id"] for r in cuerpo["references"]] == [AUTH]
    assert cuerpo["missing"] == ["TASK-1999-0001/Fantasma"]


def test_una_lista_vacia_es_422_y_no_una_consulta_a_la_nada(corpus):
    _, pedidas = corpus

    respuesta = TestClient(app).post("/v1/corpus/references", json={"references": []})

    assert respuesta.status_code == 422
    assert pedidas == []


def test_la_base_caida_es_503_y_no_un_500_sin_forma(corpus, monkeypatch):
    async def explota(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(router_module.store, "resolve", explota)

    respuesta = TestClient(app).post("/v1/corpus/references", json={"references": [AUTH]})

    assert respuesta.status_code == 503
