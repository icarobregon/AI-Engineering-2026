"""``POST /v1/corpus/references`` — el desglose de las referencias que cita el grafo.

La estimación supervisada guarda por cada componente sus ``budget_matches``: un
identificador y un total de horas. Con eso el revisor ve «79 h» y no puede juzgar
nada, porque no sabe de qué proyecto, de qué año ni de qué stack salen. Esta ruta
abre ese número: devuelve el módulo histórico entero, con las tareas cuya suma ES
ese total.

En POST y no en GET aunque sea una lectura, por dos razones que se refuerzan: se
piden VARIAS a la vez —un componente se respalda con cinco referencias y su
detalle no debería costar cinco viajes— y el identificador lleva dentro una barra
y un ampersand (``TASK-2022-0032/Authentication & Access``), que en un segmento de
ruta obliga a un doble escapado que no se gana nada teniendo.

Transporte fino: la validación vive en ``ReferencesRequest`` (422), la
autenticación en ``require_estimate_key`` (401) y la resolución en
``store/references.py``. Una referencia que el corpus ya no tiene NO es un error:
sale en ``missing``, porque «el número se apoya en algo que ya no está» es
justamente lo que hay que poder enseñar.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.api.security import require_estimate_key
from app.dependencies import get_corpus_session_factory
from app.generation.rag.schemas import (
    ReferencesRequest,
    ReferencesResponse,
    ReferenceTaskView,
    ReferenceView,
)
from app.generation.rag.store import references as store

log = structlog.get_logger()

router = APIRouter(
    prefix="/v1/corpus",
    tags=["corpus"],
    dependencies=[Depends(require_estimate_key)],
)


@router.post("/references", response_model=ReferencesResponse)
async def resolve_references(
    payload: ReferencesRequest,
    session_factory=Depends(get_corpus_session_factory),
) -> ReferencesResponse:
    """Resuelve cada identificador a su módulo histórico con el desglose."""
    try:
        async with session_factory() as session:
            encontradas = await store.resolve(session, payload.references)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo de la BBDD es 503
        # El mismo 503 que /embeddings/index/stats: es lo que el resto del
        # servicio usa para «la dependencia no está» y lo que la taxonomía de
        # errores del BFF traduce a un mensaje accionable.
        log.warning("references_unavailable", error=str(exc)[:200])
        raise HTTPException(status_code=503, detail="Corpus store unavailable") from exc

    # Se conserva el orden en el que llegaron: quien pregunta las tiene ya
    # ordenadas por distancia, y devolverlas en el orden del diccionario perdería
    # esa ordenación sin que se notara.
    vistas = [
        ReferenceView(
            reference_budget_id=r.reference_budget_id,
            budget_id=r.budget_id,
            module=r.module,
            project=r.project,
            client_sector=r.client_sector,
            year=r.year,
            main_technology=r.main_technology,
            total_hours=r.total_hours,
            tasks=[
                ReferenceTaskView(
                    component_id=t.component_id,
                    name=t.name,
                    description=t.description,
                    tech_stack=t.tech_stack,
                    complexity=t.complexity,
                    estimated_hours=t.estimated_hours,
                )
                for t in r.tasks
            ],
        )
        for ref in payload.references
        if (r := encontradas.get(ref)) is not None
    ]
    faltan = [ref for ref in payload.references if ref not in encontradas]
    if faltan:
        log.info("references_missing", count=len(faltan), sample=faltan[:3])

    return ReferencesResponse(references=vistas, missing=faltan)
