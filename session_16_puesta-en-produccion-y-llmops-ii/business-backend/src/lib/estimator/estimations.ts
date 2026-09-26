/** Session 4 — `POST /api/v1/estimate`: one transcript in, a costed breakdown out. */
import "server-only";

import { callEstimator } from "./client";
import {
  estimationResponseSchema,
  type EstimationRequest,
  type EstimationResponse,
} from "./contracts";

export async function requestEstimation(input: EstimationRequest): Promise<EstimationResponse> {
  const payload = await callEstimator<unknown>("/api/v1/estimate", {
    method: "POST",
    body: input,
  });
  return estimationResponseSchema.parse(payload);
}
