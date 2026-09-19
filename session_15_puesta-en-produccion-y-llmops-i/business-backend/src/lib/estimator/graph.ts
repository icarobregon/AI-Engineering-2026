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
  graphEstimateResponseSchema,
  graphStateSchema,
  type GraphEstimateResponse,
  type GraphState,
  type HumanDecision,
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
