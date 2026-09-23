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
        status_code = 200
        is_error = False

        def json(self):
            return body

    async def _post(self, url, *, headers=None, json=None):
        sent.update(url=url, headers=headers, json=json)
        return _Response()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)
    return sent


# --- La misma Jev por el AI Gateway de Vercel --------------------------------
# Mismo contrato de petición y respuesta; cambia la puerta, el bearer y el id.


def test_the_gateway_model_id_is_recognised_too() -> None:
    # Directo contra TypeSafe el id es `jev-latest`; por el AI Gateway de Vercel
    # es `typesafe-ai/jev`, con el prefijo del proveedor. Se comparan ya
    # normalizados, así que una sola regla cubre las dos puertas.
    assert is_decision_model("typesafe-ai/jev")
    assert is_decision_model("jev-latest")
    # Y el prefijo no abre la puerta a cualquier cosa con barra.
    assert not is_decision_model("anthropic/claude-sonnet-5")
    assert not is_decision_model("openai/gpt-5.6-sol")


async def test_the_gateway_base_url_lands_on_the_same_path(monkeypatch) -> None:
    client = TypeSafeClient(
        api_key="vck_test", api_base="https://ai-gateway.vercel.sh/typesafe", timeout=5
    )
    sent = _patch_post(monkeypatch, _body(model="typesafe-ai/jev"))

    await client.choose(state="s", model="typesafe-ai/jev", instructions="i", criteria=CRITERIA)

    # Es la URL que documenta Vercel: base + /v1/systemone. El cliente la compone,
    # nunca la lleva escrita, y por eso cambiar de puerta son dos variables.
    assert sent["url"] == "https://ai-gateway.vercel.sh/typesafe/v1/systemone"
    assert sent["headers"]["Authorization"] == "Bearer vck_test"


def test_the_gateway_rate_wins_over_our_estimate() -> None:
    # Cuando delante hay una pasarela que ya ha contabilizado la llamada, su
    # número manda sobre el nuestro: nuestra tabla se cura a mano.
    body = _body()
    body["provider_metadata"] = {
        "gateway": {"cost": "0.00001155", "marketCost": "0.00001155", "generationId": "gen_x"}
    }

    meta = _meta_from(body, "typesafe-ai/jev", body["answers"]["next_agent"])

    assert meta["cost_usd"] == 0.00001155
    # Facturado y tarifa coinciden, así que no hay descuento que anotar.
    assert "billed_usd" not in meta


def test_free_credits_do_not_make_the_router_look_free() -> None:
    # Medido contra la API real: con créditos gratis la pasarela devuelve
    # cost="0" y marketCost="0.00001302". Coger el facturado dejaría `cost_usd`
    # en cero — un número que un panel suma, y la comparación contra gpt-5-mini
    # sin sentido. Manda la tarifa; el descuento se anota aparte.
    body = _body()
    body["provider_metadata"] = {"gateway": {"cost": "0", "marketCost": "0.00001302"}}

    meta = _meta_from(body, "typesafe-ai/jev", body["answers"]["next_agent"])

    assert meta["cost_usd"] == 0.00001302
    assert meta["billed_usd"] == 0.0


def test_an_unparseable_gateway_amount_falls_back_to_our_table() -> None:
    body = _body()
    body["provider_metadata"] = {"gateway": {"cost": "gratis", "marketCost": "gratis"}}

    meta = _meta_from(body, "typesafe-ai/jev", body["answers"]["next_agent"])

    # Se queda la estimación propia antes que perder el coste: lo que no puede
    # pasar es que un campo raro de la pasarela deje la llamada sin precio.
    assert meta["cost_usd"] == pytest.approx(1.3e-05, rel=1e-9)
    assert "billed_usd" not in meta


# --- Un fallo tiene que decir POR QUE ----------------------------------------


def _patch_error(monkeypatch, status: int, body, text: str = ""):
    class _Response:
        status_code = status
        is_error = True

        def json(self):
            if body is None:
                raise ValueError("no json")
            return body

        @property
        def text(self):
            return text

    async def _post(self, url, *, headers=None, json=None):
        return _Response()

    monkeypatch.setattr("httpx.AsyncClient.post", _post)


async def test_an_http_error_carries_the_bodys_message(monkeypatch) -> None:
    # El primer 403 real de este cliente decia solo "403 Forbidden", y el cuerpo
    # decia "requires a valid credit card on file". Esa es la diferencia entre
    # diagnosticarlo en un minuto y sospechar del id del modelo durante media
    # hora, asi que el mensaje viaja en la excepcion.
    client = TypeSafeClient(
        api_key="k", api_base="https://ai-gateway.vercel.sh/typesafe", timeout=5
    )
    _patch_error(
        monkeypatch,
        403,
        {
            "error": {
                "message": "AI Gateway requires a valid credit card on file to service requests.",
                "type": "customer_verification_required",
            }
        },
    )

    with pytest.raises(TypeSafeUnavailable, match="credit card"):
        await client.choose(state="s", model="typesafe-ai/jev", instructions="i", criteria=CRITERIA)


async def test_typesafes_own_error_shape_is_read_too(monkeypatch) -> None:
    # TypeSafe directo anida distinto que la pasarela de Vercel.
    client = TypeSafeClient(api_key="k", api_base="https://api.typesafe.ai", timeout=5)
    _patch_error(
        monkeypatch,
        400,
        {
            "message": "questions.q.type: expected one of 'noul', 'choice', 'score'",
            "error_type": "invalid_request",
        },
    )

    with pytest.raises(TypeSafeUnavailable, match="expected one of"):
        await client.choose(state="s", model="jev-latest", instructions="i", criteria=CRITERIA)


async def test_a_non_json_error_falls_back_to_the_raw_text(monkeypatch) -> None:
    # Un intermediario puede contestar HTML; el fallo sigue teniendo que decir algo.
    client = TypeSafeClient(api_key="k", api_base="https://api.typesafe.ai", timeout=5)
    _patch_error(monkeypatch, 502, None, text="<html>Bad Gateway</html>")

    with pytest.raises(TypeSafeUnavailable, match="Bad Gateway"):
        await client.choose(state="s", model="jev-latest", instructions="i", criteria=CRITERIA)
