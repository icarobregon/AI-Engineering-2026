/** The active model, for the badge in the navbar. Degrades to null, never throws. */
import "server-only";

import { callEstimator } from "./client";
import { modelsConfigSchema } from "./contracts";

export async function currentPrimaryModel(): Promise<string | null> {
  try {
    const payload = await callEstimator<unknown>("/api/v1/config/models", {
      token: "none",
      timeoutMs: 3_000,
    });
    const parsed = modelsConfigSchema.parse(payload);
    // The knobs are keyed by their env-var name, uppercase.
    return parsed.models.PRIMARY_MODEL?.effective ?? null;
  } catch {
    // A missing badge is better than a dashboard that will not render because
    // the AI service is restarting.
    return null;
  }
}
