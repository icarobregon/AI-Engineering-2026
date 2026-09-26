"""``/v1/estimate/graph`` — transcript → estimate, via the multi-agent system.

Three verbs now. Starting a run, releasing one that stopped for a human, and
reading where one stands. Thin transport, like every other router here: it
resolves the thread id, invokes the compiled graph and maps the state it gets
back onto the response shape the business backend already consumes. No
orchestration lives in this file — if it did, the graph would not be the thing
that owns the flow.

``thread_id = estimation_id`` is the identifier that crosses all three layers,
the checkpointer and the traces. It is what makes a retry safe and what lets a
reviewer in a different process, on a different day, resume a run this one
started.
"""

from __future__ import annotations

import uuid

import logfire
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from typing import Literal

from pydantic import BaseModel, Field
from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from app.api.rate_limiting import limiter
from app.api.security import require_estimate_key
from app.config import get_settings
from app.dependencies import get_llm_wrapper
from app.domain.graph.band import historical_band
from app.domain.graph.progress import RUN_FAILED_PREFIX, build_progress
from app.domain.proposal import ProposalNotReady, write_proposal
from app.domain.schemas.graph_estimation import (
    CommercialProposal,
    GraphEstimateRequest,
    GraphEstimateResponse,
    HumanDecision,
)

log = structlog.get_logger()

router = APIRouter(prefix="/v1/estimate", tags=["estimate"])


def _require_graph(request: Request):
    """The compiled graph, or a 503 saying why it is not there.

    The graph is built in the lifespan; None means its checkpointer could not be
    opened. Saying so is better than quietly running unpersisted — and with a
    human gate in the flow, unpersisted means a pause that can never resume.
    """
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="The estimation graph is not available.")
    return graph


def _pending_review(snapshot) -> dict | None:
    """The payload of the interrupt this thread is waiting on, if any.

    Read from the snapshot rather than from an invoke's ``__interrupt__``,
    because the interesting case is the one where we must NOT invoke: a client
    retrying an estimation that is already sitting in front of a reviewer.
    """
    for interrupt in getattr(snapshot, "interrupts", None) or ():
        return interrupt.value
    for task in getattr(snapshot, "tasks", None) or ():
        for interrupt in getattr(task, "interrupts", None) or ():
            return interrupt.value
    return None


def _config(estimation_id: str) -> dict:
    settings = get_settings()
    return {
        "configurable": {"thread_id": estimation_id},
        # The safety net, not the strategy: LangGraph counts this per invoke, so
        # a run that pauses and resumes gets a fresh budget. What actually bounds
        # a run is routing_steps, which lives in the checkpointed state.
        "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
    }


def _respond(estimation_id: str, values: dict) -> GraphEstimateResponse:
    return GraphEstimateResponse(
        estimate=values.get("estimate"),
        status=values.get("status") or "needs_review",
        estimation_id=estimation_id,
        errors=values.get("errors") or [],
    )


def _failed(estimation_id: str, exc: Exception) -> HTTPException:
    if isinstance(exc, GraphRecursionError):
        # Distinct from an LLM failure and diagnosed differently: this one means
        # the routing budget and the recursion limit are out of step with each
        # other, not that a provider was down.
        log.error("graph_recursion_exceeded", estimation_id=estimation_id, error=str(exc)[:300])
    else:
        log.error(
            "graph_estimate_failed",
            estimation_id=estimation_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
    return HTTPException(status_code=502, detail="Failed to produce an estimate.")


@router.post(
    "/graph",
    response_model=GraphEstimateResponse,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def estimate_via_graph(
    request: Request, payload: GraphEstimateRequest
) -> GraphEstimateResponse:
    """Run the estimation system over one transcript."""
    graph = _require_graph(request)
    estimation_id = payload.estimation_id or str(uuid.uuid4())
    config = _config(estimation_id)

    try:
        snapshot = await graph.aget_state(config)

        # A thread that already finished is ANSWERED, not re-run. Re-invoking it
        # opens a fresh superstep over the persisted channels, and the
        # accumulators (budget_matches, errors, routing_trail) append the second
        # run's writes to the first's: the evidence doubles, and a retry whose
        # retrieval failed still finds the previous run's matches and certifies
        # components as grounded on references it never retrieved.
        if snapshot.values and not snapshot.next:
            log.info("graph_estimate_replayed", estimation_id=estimation_id)
            return _respond(estimation_id, snapshot.values)

        # A thread waiting on a reviewer is REPORTED, not restarted. This is the
        # same duplication bug wearing a different hat: an interrupted thread has
        # values AND a non-empty `next`, so the finished-check above lets it
        # through, and invoking it here would run the whole graph again while the
        # reviewer still has the first run on their screen.
        if review_payload := _pending_review(snapshot):
            log.info("graph_estimate_awaiting_review", estimation_id=estimation_id)
            return GraphEstimateResponse(
                estimate=None,
                status="awaiting_human_review",
                estimation_id=estimation_id,
                errors=snapshot.values.get("errors") or [],
                review_payload=review_payload,
            )

        # Only new input goes in. Passing accumulator fields would make their
        # reducers concatenate them with what is already persisted.
        with logfire.span(
            "estimation graph run", thread_id=estimation_id, estimation_id=estimation_id
        ):
            result = await graph.ainvoke(
                {"transcript": payload.transcript, "estimation_id": estimation_id}, config
            )
    except Exception as exc:  # noqa: BLE001 - transport boundary
        raise _failed(estimation_id, exc) from exc

    # ainvoke returns __interrupt__ as a list, astream yields it as a tuple.
    if interrupts := result.get("__interrupt__"):
        log.info("graph_estimate_paused", estimation_id=estimation_id)
        return GraphEstimateResponse(
            estimate=None,
            status="awaiting_human_review",
            estimation_id=estimation_id,
            errors=result.get("errors") or [],
            review_payload=list(interrupts)[0].value,
        )

    return _respond(estimation_id, result)


@router.post(
    "/graph/{estimation_id}/resume",
    response_model=GraphEstimateResponse,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def resume_estimation(
    request: Request, estimation_id: str, payload: HumanDecision
) -> GraphEstimateResponse:
    """Release a paused estimation with the reviewer's decision."""
    graph = _require_graph(request)
    config = _config(estimation_id)

    try:
        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            raise HTTPException(status_code=404, detail=f"No estimation {estimation_id!r}.")

        # Two reviewers approving the same estimate must not produce two runs.
        # Answering the second one with the decided result makes the endpoint
        # idempotent without a lock: the record of who decided first is in
        # human_decision, and arbitrating between reviewers is the business
        # backend's job, not this service's.
        if not _pending_review(snapshot):
            log.info("graph_resume_noop", estimation_id=estimation_id, reason="nothing pending")
            return _respond(estimation_id, snapshot.values)

        with logfire.span(
            "estimation graph resume", thread_id=estimation_id, estimation_id=estimation_id
        ):
            # A dict, always: Command(resume=None) raises UnboundLocalError deep
            # inside LangGraph 1.0.1, and `action` is required, so model_dump()
            # is never empty.
            result = await graph.ainvoke(Command(resume=payload.model_dump()), config)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - transport boundary
        raise _failed(estimation_id, exc) from exc

    log.info("graph_estimate_resumed", estimation_id=estimation_id, action=payload.action)
    return _respond(estimation_id, result)


@router.get(
    "/graph/{estimation_id}/state",
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("30/minute")
async def get_estimation_state(request: Request, estimation_id: str) -> dict:
    """Where one estimation stands: its state, what runs next, what it is waiting on."""
    graph = _require_graph(request)
    snapshot = await graph.aget_state(_config(estimation_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No estimation {estimation_id!r}.")

    return {
        "estimation_id": estimation_id,
        "values": snapshot.values,
        "next": list(snapshot.next or ()),
        "review_payload": _pending_review(snapshot),
        # DERIVADA, no almacenada: la banda no es un campo del estado, se calcula
        # de `components` + `budget_matches`. Va aquí, fuera de `values`, para que
        # eso se note. Y se calcula con la MISMA función que usa la puerta humana,
        # no con una copia: la regla de escalado por cobertura tiene una sutileza
        # —una banda construida con las mismas referencias que fijaron el precio
        # contiene el resultado por construcción— y dos implementaciones de eso
        # acaban dando dos bandas distintas para la misma ejecución.
        "historical_band": historical_band(
            snapshot.values.get("components") or [],
            snapshot.values.get("budget_matches") or [],
        ),
    }


class GraphStartResponse(BaseModel):
    """The answer to "start this", which is no longer the answer to "what is it"."""

    estimation_id: str = Field(description="The thread_id this run is checkpointed under.")
    status: Literal[
        "running",
        "awaiting_human_review",
        "validated",
        "needs_review",
        "routing_budget_exhausted",
    ] = Field(description="'running' when this call launched work; otherwise what is already known.")
    started: bool = Field(description="Whether this call actually launched a run.")


async def _run_detached(graph, estimation_id: str, transcript: str) -> None:
    """Run the graph outside the request that asked for it.

    A crash in here has no response to fail: the client has been answered and is
    polling. So the failure is written into the run's own ``errors`` channel,
    where it is persisted like everything else and the progress verb can report
    it. Without that a dead run is indistinguishable from a slow one — ``next``
    still names the node that died — and the screen polls it forever.
    """
    config = _config(estimation_id)
    try:
        with logfire.span(
            "estimation graph run (detached)", thread_id=estimation_id, estimation_id=estimation_id
        ):
            await graph.ainvoke({"transcript": transcript, "estimation_id": estimation_id}, config)
    except Exception as exc:  # noqa: BLE001 - nothing above this to catch it
        log.error(
            "graph_detached_run_failed",
            estimation_id=estimation_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        try:
            await graph.aupdate_state(
                config,
                {"errors": [f"{RUN_FAILED_PREFIX}{type(exc).__name__}: {str(exc)[:200]}"]},
            )
        except Exception as write_failure:  # noqa: BLE001
            # The checkpointer is the thing that just died in most of these. Say
            # so plainly rather than leaving a silent failure to look like a run
            # that is simply taking its time.
            log.error(
                "graph_failure_not_persisted",
                estimation_id=estimation_id,
                error=str(write_failure)[:200],
            )


@router.post(
    "/graph/start",
    response_model=GraphStartResponse,
    status_code=202,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def start_estimation(
    request: Request, payload: GraphEstimateRequest, background: BackgroundTasks
) -> GraphStartResponse:
    """Launch a run and answer immediately. Poll ``/progress`` for the rest.

    The sibling ``POST /graph`` holds the HTTP connection open for as long as the
    whole multi-agent system takes, which is minutes. That shape has no room for
    a progress feed — there is nothing to poll while the caller is blocked on the
    answer — and it makes every client's read timeout a ceiling on how long an
    estimation may legitimately take.

    The three branches are the sibling's, and for the same reasons: a finished
    thread is answered, a paused one is reported, and only a genuinely new one is
    launched. Re-invoking either of the other two appends to every accumulator.
    """
    graph = _require_graph(request)
    estimation_id = payload.estimation_id or str(uuid.uuid4())

    try:
        snapshot = await graph.aget_state(_config(estimation_id))
    except Exception as exc:  # noqa: BLE001 - transport boundary
        raise _failed(estimation_id, exc) from exc

    if snapshot.values and not snapshot.next:
        log.info("graph_start_replayed", estimation_id=estimation_id)
        return GraphStartResponse(
            estimation_id=estimation_id,
            status=snapshot.values.get("status") or "needs_review",
            started=False,
        )

    if _pending_review(snapshot):
        log.info("graph_start_awaiting_review", estimation_id=estimation_id)
        return GraphStartResponse(
            estimation_id=estimation_id, status="awaiting_human_review", started=False
        )

    background.add_task(_run_detached, graph, estimation_id, payload.transcript)
    log.info("graph_start_accepted", estimation_id=estimation_id)
    return GraphStartResponse(estimation_id=estimation_id, status="running", started=True)


@router.get(
    "/graph/{estimation_id}/progress",
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("120/minute")
async def get_estimation_progress(request: Request, estimation_id: str) -> dict:
    """What has happened so far, node by node, with durations.

    Reads the checkpoint HISTORY rather than the state: the state has no
    timestamps at all, and the checkpointer has been stamping one per superstep
    all along. The rate limit is the polling one — this is the verb a screen
    calls every couple of seconds, and it must not share a budget with the verbs
    that spend money.
    """
    graph = _require_graph(request)
    config = _config(estimation_id)

    snapshot = await graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No estimation {estimation_id!r}.")

    # aget_state_history yields newest first; the timeline reads oldest first.
    history = [item async for item in graph.aget_state_history(config)]
    history.reverse()

    return {
        "estimation_id": estimation_id,
        **build_progress(history, review_payload=_pending_review(snapshot)),
    }



@router.post(
    "/graph/{estimation_id}/proposal",
    response_model=CommercialProposal,
    dependencies=[Depends(require_estimate_key)],
)
@limiter.limit("10/minute")
async def write_commercial_proposal(request: Request, estimation_id: str) -> CommercialProposal:
    """Draft the client-facing proposal for a run that already has an estimate.

    A separate verb over the finished checkpoint, never a graph node: it reads
    the state, writes prose and changes nothing. That is what makes it free of
    the routing budget and retryable on its own — a proposal whose tone missed
    can be redrafted without re-running the estimation and paying for it again.

    Nothing is persisted here. Which drafts existed, which one was sent and who
    approved it is business history, and it lives in the business backend for
    the same reason ``human_decision`` does.
    """
    graph = _require_graph(request)
    snapshot = await graph.aget_state(_config(estimation_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail=f"No estimation {estimation_id!r}.")

    # A run in front of a reviewer has an estimate, and writing a client document
    # from a figure nobody has approved yet is exactly the accident this check
    # exists to prevent.
    if _pending_review(snapshot):
        raise HTTPException(
            status_code=409,
            detail="The estimation is still waiting on a human decision.",
        )

    settings = get_settings()
    try:
        return await write_proposal(
            get_llm_wrapper(timeout=settings.GRAPH_LLM_TIMEOUT),
            model=settings.GRAPH_PROPOSAL_MODEL,
            state=snapshot.values,
            estimation_id=estimation_id,
        )
    except ProposalNotReady as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - transport boundary
        log.error(
            "proposal_failed",
            estimation_id=estimation_id,
            error_type=type(exc).__name__,
            error=str(exc)[:300],
        )
        raise HTTPException(status_code=502, detail="Failed to draft the proposal.") from exc


class GraphDiagramResponse(BaseModel):
    """El grafo multi-agente, dibujado desde el grafo COMPILADO."""

    mermaid: str = Field(description="Diagrama en sintaxis Mermaid, listo para renderizar.")
    nodes: list[str] = Field(description="Nodos, sin los pseudonodos __start__ / __end__.")
    entry_point: str = Field(description="Primer nodo real tras __start__.")


@router.get(
    "/graph/diagram",
    response_model=GraphDiagramResponse,
    dependencies=[Depends(require_estimate_key)],
)
async def graph_diagram(request: Request) -> GraphDiagramResponse:
    """El diagrama del grafo, derivado de la topología real.

    No es un dibujo mantenido a mano: sale del grafo ya compilado, así que no
    puede desincronizarse del código. Desde la Sesión 14 las aristas ya no se
    declaran —viven dentro de cada ``Command``— y LangGraph las reconstruye
    resolviendo la anotación ``Command[Literal[...]]`` de cada nodo. Eso convierte
    este endpoint en algo más que una ilustración: si alguien mueve un import de
    ``Command`` o ``Literal`` a ``TYPE_CHECKING``, la anotación deja de resolver y
    las aristas DESAPARECEN de aquí, que es la señal más temprana de un fallo que
    por lo demás es silencioso (un ``goto`` a un nodo inexistente no levanta nada).
    """
    graph = _require_graph(request)
    dibujo = graph.get_graph()
    nodos = [n for n in dibujo.nodes if not n.startswith("__")]
    return GraphDiagramResponse(
        mermaid=dibujo.draw_mermaid(),
        nodes=nodos,
        # El punto de entrada se lee del grafo, no se escribe aquí: si algún día
        # START deja de apuntar al supervisor, esto lo dice solo.
        entry_point=next(
            (e.target for e in dibujo.edges if e.source == "__start__"),
            nodos[0] if nodos else "",
        ),
    )
