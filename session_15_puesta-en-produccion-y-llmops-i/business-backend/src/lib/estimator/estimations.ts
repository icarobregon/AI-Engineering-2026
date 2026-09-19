/** Session 4 — `POST /api/v1/estimate`: one transcript in, a costed breakdown out. */
import "server-only";

import { callEstimator } from "./client";
import {
  estimationResponseSchema,
  type EstimationRequest,
  type EstimationResponse,
} from "./contracts";

export async function requestEstimation(input: EstimationRequest): Promise<EstimationResponse> {
  // This route is not key-protected in the estimator, unlike the graph one.
  const payload = await callEstimator<unknown>("/api/v1/estimate", {
    method: "POST",
    body: input,
    token: "none",
  });
  return estimationResponseSchema.parse(payload);
}
