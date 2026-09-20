/** Session 7 — `POST /embeddings/compare`: the chunking strategy laboratory. */
import "server-only";

import budgets from "@/lib/data/budgets-sample.json";
import { callEstimator } from "./client";
import { compareResponseSchema, type CompareResponse, type StrategyName } from "./contracts";

/**
 * The corpus travels in the request.
 *
 * There is no endpoint that serves it, so the seventeen sample budgets live here
 * as a data file — the same choice the reference app makes with its own static
 * copy. It is ~28 KB of fictitious budgets, which is small enough to post.
 */
export function corpusSize(): number {
  return budgets.length;
}

/**
 * The paid strategies call a provider once per component, so a run with them can
 * take minutes. The AI service handler is synchronous and occupies a worker for
 * the whole run, which is why this is opt-in in the UI rather than the default.
 */
export async function compareChunking(input: {
  strategies: StrategyName[];
  queries: string[];
  topK: number;
}): Promise<CompareResponse> {
  const payload = await callEstimator<unknown>("/embeddings/compare", {
    method: "POST",
    // This route carries no authentication in the AI service.
    timeoutMs: 600_000,
    body: {
      budgets,
      // Always explicit: an empty list means ALL EIGHT on the server, and two of
      // those cost real money.
      strategies: input.strategies,
      queries: input.queries,
      top_k: input.topK,
    },
  });
  return compareResponseSchema.parse(payload);
}
