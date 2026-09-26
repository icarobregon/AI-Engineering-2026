/**
 * Sessions 13-14 — `/v1/estimate/graph`: the supervised estimate and its gate.
 *
 * Two verbs carry the whole flow. `start` is idempotent by `estimation_id`: the
 * same id returns what is already known for that run rather than estimating
 * twice, which is what makes a retry safe. `resume` releases a run that stopped
 * in front of a person.
 */
import "server-only";

import { callEstimator } from "./client";
import {
  commercialProposalSchema,
  graphEstimateResponseSchema,
  graphStartResponseSchema,
  graphStateSchema,
  referencesResponseSchema,
  runProgressSchema,
  type CommercialProposal,
  type GraphEstimateResponse,
  type GraphStartResponse,
  type GraphState,
  type HumanDecision,
  type ReferencesResponse,
  type RunProgress,
} from "./contracts";

export async function startSupervisedEstimation(
  transcript: string,
  estimationId: string,
): Promise<GraphEstimateResponse> {
  const payload = await callEstimator<unknown>("/v1/estimate/graph", {
    method: "POST",
    body: { transcript, estimation_id: estimationId },
  });
  return graphEstimateResponseSchema.parse(payload);
}

export async function resumeSupervisedEstimation(
  estimationId: string,
  decision: HumanDecision,
): Promise<GraphEstimateResponse> {
  const payload = await callEstimator<unknown>(
    `/v1/estimate/graph/${encodeURIComponent(estimationId)}/resume`,
    { method: "POST", body: decision },
  );
  return graphEstimateResponseSchema.parse(payload);
}

/**
 * Where a run stands, including the routing trail — which the start/resume
 * responses do not carry. Separate call on purpose: the trail is diagnostic,
 * so the inbox does not pay for it on every row.
 */
export async function getSupervisedRunState(estimationId: string): Promise<GraphState> {
  const payload = await callEstimator<unknown>(
    `/v1/estimate/graph/${encodeURIComponent(estimationId)}/state`,
    { timeoutMs: 15_000 },
  );
  return graphStateSchema.parse(payload);
}

/**
 * Sesión 15 — arrancar sin quedarse esperando.
 *
 * `startSupervisedEstimation` mantiene la petición abierta los minutos que dure
 * el sistema multiagente. Ésta contesta 202 y deja el run corriendo por detrás,
 * que es lo que permite sondear el avance y lo que evita que el timeout de
 * lectura de este cliente sea un techo para la estimación.
 */
export async function launchSupervisedEstimation(
  transcript: string,
  estimationId: string,
): Promise<GraphStartResponse> {
  const payload = await callEstimator<unknown>("/v1/estimate/graph/start", {
    method: "POST",
    body: { transcript, estimation_id: estimationId },
    // Corto a propósito: si el servicio no acepta el arranque en unos segundos,
    // no lo va a aceptar. El trabajo largo ya no vive en esta llamada.
    timeoutMs: 20_000,
  });
  return graphStartResponseSchema.parse(payload);
}

/** Qué ha pasado hasta ahora, nodo a nodo. Es el verbo que se llama en bucle. */
export async function getSupervisedRunProgress(estimationId: string): Promise<RunProgress> {
  const payload = await callEstimator<unknown>(
    `/v1/estimate/graph/${encodeURIComponent(estimationId)}/progress`,
    { timeoutMs: 15_000 },
  );
  return runProgressSchema.parse(payload);
}

/**
 * Redacta (o vuelve a redactar) la propuesta comercial de un run terminado.
 *
 * No re-ejecuta el grafo, así que reintentarla cuesta una generación y no una
 * estimación entera. El timeout es el largo: es una llamada a un modelo.
 */
export async function draftCommercialProposal(estimationId: string): Promise<CommercialProposal> {
  const payload = await callEstimator<unknown>(
    `/v1/estimate/graph/${encodeURIComponent(estimationId)}/proposal`,
    { method: "POST", timeoutMs: 180_000 },
  );
  return commercialProposalSchema.parse(payload);
}

/**
 * El desglose de las referencias que respaldan un componente.
 *
 * En lote porque así se piden: un componente se apoya en cinco y abrir su
 * detalle no debería costar cinco viajes. Es una lectura del corpus, no del
 * grafo, así que no tiene nada que ver con el estado del run y se puede pedir
 * igual para una estimación terminada hace semanas.
 */
export async function resolveReferences(referenceBudgetIds: string[]): Promise<ReferencesResponse> {
  const payload = await callEstimator<unknown>("/v1/corpus/references", {
    method: "POST",
    body: { references: referenceBudgetIds },
  });
  return referencesResponseSchema.parse(payload);
}
