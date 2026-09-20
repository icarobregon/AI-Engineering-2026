"use server";

import { compareChunking } from "@/lib/estimator/chunking";
import {
  chunkingStrategies,
  type CompareResponse,
  type StrategyName,
} from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";

export type FormState = { error: string | null; result: CompareResponse | null };

const known = new Set<string>(chunkingStrategies.map((s) => s.name));

export async function runComparison(_previous: FormState, formData: FormData): Promise<FormState> {
  // Deduplicated and validated here: a duplicate runs twice on the server and
  // collapses into one key of the result, and an unknown name comes back as a
  // 400 rather than a validation error.
  const strategies = [...new Set(formData.getAll("strategies").map(String))].filter((s) =>
    known.has(s),
  ) as StrategyName[];

  if (strategies.length === 0) {
    return { error: "Elige al menos una estrategia.", result: null };
  }

  const queries = String(formData.get("queries") ?? "")
    .split("\n")
    .map((q) => q.trim())
    .filter(Boolean);

  const topK = Math.min(10, Math.max(1, Number(formData.get("top_k") ?? 3) || 3));

  try {
    const result = await compareChunking({ strategies, queries, topK });
    return { error: null, result };
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage, result: null };
    throw error;
  }
}
