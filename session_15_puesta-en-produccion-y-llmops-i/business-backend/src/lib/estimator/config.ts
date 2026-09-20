/** Runtime model configuration — the knobs the AI service can change in flight. */
import "server-only";

import { callEstimator } from "./client";
import { modelsConfigSchema, type ModelsConfig } from "./contracts";

/**
 * These four routes carry no authentication in the AI service, so the token is
 * not sent. That is also why the business backend must never proxy them
 * blindly: whoever reaches this app can change the model the whole system uses.
 * Today the app has no users, which is a documented limitation — see the README.
 */
export async function getModelsConfig(): Promise<ModelsConfig> {
  const payload = await callEstimator<unknown>("/api/v1/config/models");
  return modelsConfigSchema.parse(payload);
}

/**
 * Partial update. A `null` clears the override and restores the `.env` default;
 * an empty string is NOT a reset — it reaches the catalogue and comes back as a
 * 422 — so callers turn "" into null before getting here.
 */
export async function updateModels(models: Record<string, string | null>): Promise<ModelsConfig> {
  const payload = await callEstimator<unknown>("/api/v1/config/models", {
    method: "PUT",
    body: { models },
    timeoutMs: 10_000,
  });
  return modelsConfigSchema.parse(payload);
}

/** The active primary model, for the navbar badge. Degrades to null, never throws. */
export async function currentPrimaryModel(): Promise<string | null> {
  try {
    const config = await getModelsConfig();
    return config.models.PRIMARY_MODEL?.effective ?? null;
  } catch {
    // A missing badge is better than a dashboard that will not render because
    // the AI service is restarting.
    return null;
  }
}
