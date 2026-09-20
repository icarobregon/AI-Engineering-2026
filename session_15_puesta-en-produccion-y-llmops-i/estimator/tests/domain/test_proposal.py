"""The commercial proposal writer.

What these tests defend is the split the whole graph is built on: **the numbers
are the tool's, the prose is the model's**. A proposal is the one document where
breaking that rule is invisible — nobody diffs a paragraph against an estimate —
so the checks here are about what reaches the prompt, not about how it reads.
"""

from __future__ import annotations

import pytest

from app.domain.proposal import ProposalNotReady, write_proposal
from app.domain.schemas.graph_estimation import CommercialProposal

PROPOSAL = CommercialProposal(
    title="Propuesta · RUTA",
    executive_summary="Resumen.",
    scope=["Backend — 120 h"],
    assumptions=["El gemelo digital no tiene precedente."],
    body_markdown="## Contexto\n\nTexto.",
)


class FakeLLM:
    """Records the prompt it was handed. ``complete_structured`` is sync on
    purpose: that is what the real wrapper is, and ``structured_call`` runs it on
    a worker thread precisely because of it."""

    def __init__(self):
        self.system_prompt = ""
        self.user_message = ""
        self.model = ""

    def complete_structured(self, *, system_prompt, user_message, response_model, **kwargs):
        self.system_prompt = system_prompt
        self.user_message = user_message
        self.model = kwargs.get("model_override", "")
        return PROPOSAL, {"model": self.model, "latency_ms": 12}


def state(**overrides) -> dict:
    base = {
        "estimate": {
            "project": "RUTA",
            "total_hours": 160.0,
            "notes": "Falta definir la pasarela de pago.",
            "components": [
                {
                    "component_id": "c1",
                    "name": "Backend de pedidos",
                    "estimated_hours": 160.0,
                    "grounded": True,
                    "rationale": "Dos presupuestos comparables.",
                },
                {
                    "component_id": "c2",
                    "name": "Gemelo digital 3D",
                    "estimated_hours": 0.0,
                    "grounded": False,
                    "rationale": "Ningún presupuesto histórico se le parece.",
                },
            ],
        },
        "components": [
            {"id": "c1", "name": "Backend de pedidos"},
            {"id": "c2", "name": "Gemelo digital 3D"},
        ],
        "budget_matches": [
            {"component_id": "c1", "amount": 140.0},
            {"component_id": "c1", "amount": 180.0},
        ],
        "validation": {"concerns": ["no evidence for Gemelo digital 3D"]},
        "confidence": 0.44,
    }
    base.update(overrides)
    return base


async def _write(llm, **overrides):
    return await write_proposal(llm, model="gpt-4o", state=state(**overrides), estimation_id="EST-1")


@pytest.mark.asyncio
async def test_a_run_without_an_estimate_refuses_instead_of_inventing_one():
    # The endpoint turns this into a 409. Writing a client document from an empty
    # estimate is the failure that must never be silent.
    with pytest.raises(ProposalNotReady):
        await write_proposal(FakeLLM(), model="gpt-4o", state={}, estimation_id="EST-1")


@pytest.mark.asyncio
async def test_an_estimate_with_no_components_also_refuses():
    with pytest.raises(ProposalNotReady):
        await write_proposal(
            FakeLLM(),
            model="gpt-4o",
            state={"estimate": {"project": "RUTA", "total_hours": 0.0, "components": []}},
            estimation_id="EST-1",
        )


@pytest.mark.asyncio
async def test_the_hours_reach_the_prompt_verbatim():
    llm = FakeLLM()
    await _write(llm)

    assert "160.0 horas" in llm.user_message
    assert "160.0 h" in llm.user_message


@pytest.mark.asyncio
async def test_the_engineer_days_are_computed_here_never_asked_for():
    """160h / 8 = 20 jornadas. If the model were asked to divide, a proposal could
    quote a figure the estimate does not contain."""
    llm = FakeLLM()
    await _write(llm)

    assert "20.0 jornadas" in llm.user_message
    assert "no inventas ni derivas ninguna cifra" in llm.system_prompt


@pytest.mark.asyncio
async def test_a_component_without_precedent_is_flagged_to_the_writer():
    llm = FakeLLM()
    await _write(llm)

    assert "Gemelo digital 3D — 0.0 h — SIN precedente histórico comparable" in llm.user_message
    assert "respaldado por presupuestos históricos" in llm.user_message


@pytest.mark.asyncio
async def test_the_band_is_recomputed_from_the_state():
    """It is not read from the interrupt payload: a run that never paused has no
    payload, and that is the common case."""
    llm = FakeLLM()
    await _write(llm)

    # c1 priced between 140 and 180, scaled by coverage (1 of 2 components).
    assert "entre 280.0 y 360.0 horas" in llm.user_message


@pytest.mark.asyncio
async def test_a_run_with_no_matches_at_all_simply_omits_the_reference():
    llm = FakeLLM()
    await _write(llm, budget_matches=[])

    assert "referencia_historica" not in llm.user_message


@pytest.mark.asyncio
async def test_the_validators_concerns_travel_to_the_writer():
    llm = FakeLLM()
    await _write(llm)

    assert "no evidence for Gemelo digital 3D" in llm.user_message
    assert "Confianza de la estimación: 0.44" in llm.user_message


@pytest.mark.asyncio
async def test_an_unknown_confidence_is_not_reported_as_zero():
    # "I don't know" and "zero" ask for different sentences, and a 0.00 in the
    # prompt would have the writer apologise for a certainty nobody measured.
    llm = FakeLLM()
    await _write(llm, confidence=None)

    assert "Confianza de la estimación: desconocida" in llm.user_message


@pytest.mark.asyncio
async def test_a_reviewer_override_is_disclosed_not_absorbed():
    """``apply_human_decision`` stamps ``original_total_hours`` when a reviewer
    adjusts the total. A client document that quietly prints the adjusted figure
    hides a human decision the estimate itself records."""
    llm = FakeLLM()
    estimate = dict(state()["estimate"], total_hours=200.0, original_total_hours=160.0)
    await _write(llm, estimate=estimate)

    assert "un revisor ajustó este total a mano" in llm.user_message.lower()
    assert "160.0 horas" in llm.user_message


@pytest.mark.asyncio
async def test_the_model_override_is_the_one_configured():
    llm = FakeLLM()
    await _write(llm)

    assert llm.model == "gpt-4o"
