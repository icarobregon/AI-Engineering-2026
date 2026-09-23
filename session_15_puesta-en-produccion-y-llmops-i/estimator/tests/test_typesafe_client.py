"""The Jev client's contract, especially the parts the response may omit.

Network-free: everything here exercises the parsing and the accounting, which is
where this client can be wrong in a way nobody notices. The HTTP call itself is
one `httpx.post` and a `raise_for_status`.
"""

from __future__ import annotations

import pytest

from app.foundation.llm.typesafe import (
    INJECTION_GUARD,
    TypeSafeClient,
    TypeSafeUnavailable,
    _meta_from,
    is_decision_model,
)

CRITERIA = {"budget_searcher": "search again", "human_review_gate": "ask a person"}


def _body(**overrides) -> dict:
    base = {
        "model": "jev-1.13.0",
        "answers": {
            "next_agent": {
                "type": "choice",
                "choice": "human_review_gate",
                "probabilities": {"budget_searcher": 0.15, "human_review_gate": 0.85},
                "confidence": 0.82,
            }
        },
        "usage": {"input_tokens": 312, "output_tokens": 48},
    }
    return base | overrides


def test_the_decision_models_are_matched_by_shape() -> None:
    assert is_decision_model("jev-latest")
    assert is_decision_model("jev-1.13.0")
    # Y nada más: si esto se volviera cierto para un modelo de texto, ese modelo
    # se iría al endpoint equivocado con la clave equivocada.
    assert not is_decision_model("gpt-5-mini")
    assert not is_decision_model("claude-sonnet-5")


def test_usage_is_mapped_from_the_names_jev_uses() -> None:
    # Jev dice input_tokens/output_tokens; la ruta de chat dice
    # prompt_tokens/completion_tokens. Sin esta traducción los tokens se leen
    # como cero y el coste con ellos.
    meta = _meta_from(_body(), "jev-latest", _body()["answers"]["next_agent"])

    assert meta["usage"] == {"input_tokens": 312, "output_tokens": 48, "total_tokens": 360}
    # 312 tokens a 0,042 US$/millón son 1,3104e-05, y `_estimate_cost` redondea
    # a seis decimales: 1,3e-05. Jev es el primer modelo del catálogo lo bastante
    # barato para tocar ese suelo — se pierde el tercer dígito significativo, no
    # el orden de magnitud. Queda escrito aquí en vez de descubrirse sumando.
    assert meta["cost_usd"] == pytest.approx(1.3e-05, rel=1e-9)
    # Y no cero, que es lo que importa: el cero de salida es el precio real.
    assert meta["cost_usd"] > 0


def test_absent_usage_omits_the_cost_instead_of_reporting_zero() -> None:
    # `usage` y `model` son opcionales en el contrato de arriba. Un coste que se
    # lee como cero es peor que uno ausente: es un número, y un panel lo suma.
    meta = _meta_from(_body(usage=None, model=None), "jev-latest", {"choice": "x"})

    assert "cost_usd" not in meta
    assert "usage" not in meta
    # El modelo que se PIDIÓ, cuando la respuesta no dice cuál sirvió.
    assert meta["model"] == "jev-latest"


def test_the_routing_confidence_is_not_the_estimates_confidence() -> None:
    meta = _meta_from(_body(), "jev-latest", _body()["answers"]["next_agent"])

    # Nombre distinto a propósito: `confidence` a secas es la de la estimación,
    # gobierna el umbral del gate humano, y el supervisor la BORRA al mandar
    # buscar otra vez — una confianza de enrutado ahí la limpiaría la misma
    # decisión que la produjo.
    assert meta["routing_confidence"] == 0.82
    assert "confidence" not in meta


async def test_a_choice_outside_the_criteria_is_refused(monkeypatch) -> None:
    client = TypeSafeClient(api_key="k", api_base="https://api.typesafe.ai", timeout=5)
    body = _body()
    body["answers"]["next_agent"]["choice"] = "ghost_agent"
    _patch_post(monkeypatch, body)

    # Dejarla pasar la convertiría en un goto a un nodo que no existe, y eso en
    # LangGraph no levanta nada: el run termina con pinta de haber acabado.
    with pytest.raises(TypeSafeUnavailable):
        await client.choose(state="s", model="jev-latest", instructions="i", criteria=CRITERIA)


async def test_the_question_carries_the_injection_guard(monkeypatch) -> None:
    client = TypeSafeClient(api_key="k", api_base="https://api.typesafe.ai/", timeout=5)
    sent = _patch_post(monkeypatch, _body())

    choice, _ = await client.choose(
        state="s", model="jev-latest", instructions="i", criteria=CRITERIA
    )

    assert choice == "human_review_gate"
    question = sent["json"]["questions"]["next_agent"]
    # El `state` se construye con texto de transcripciones: contenido no
    # confiable que decide por dónde sigue el run.
    assert INJECTION_GUARD in question["instructions"]
    assert question["criteria"] == CRITERIA
    # La barra de más en api_base no debe duplicarse en la ruta.
    assert sent["url"] == "https://api.typesafe.ai/v1/systemone"


def _patch_post(monkeypatch, body: dict) -> dict:
    """Swap httpx.AsyncClient.post for one that records and answers ``body``."""
    sent: dict = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return body

    async def _post(self, url, *, headers=None, json=None):
        sent.update(url=url, headers=headers, json=json)
        return _Response()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    return sent
