/**
 * Folding an AI-service answer into our mirror of a supervised run.
 *
 * ONE mapping, used by both start and resume, so the persisted shape cannot
 * drift from the contract.
 *
 * The `?? current` fallbacks are not defensive noise, they fix a real hole: the
 * estimator's idempotent branches answer a repeated start (or a no-op resume)
 * with `_respond()`, which omits `review_payload`. A mapping that overwrote
 * blindly would erase the reviewer's briefing the second time anyone reloaded
 * the page, and the run would sit in the inbox with nothing to decide on.
 */
import type { GraphEstimateResponse } from "@/lib/estimator/contracts";
import type { Prisma } from "@/generated/prisma/client";

export const AWAITING_REVIEW = "awaiting_human_review";

type Current = {
  estimate?: Prisma.JsonValue | null;
  reviewPayload?: Prisma.JsonValue | null;
  confidence?: number | null;
};

export function runUpdateFrom(
  response: GraphEstimateResponse,
  current: Current = {},
): Prisma.SupervisorRunUpdateInput {
  const awaiting = response.status === AWAITING_REVIEW;
  const confidence = response.review_payload?.confidence;

  return {
    runState: awaiting ? "paused" : "completed",
    status: response.status,
    estimate: (response.estimate ?? current.estimate ?? undefined) as Prisma.InputJsonValue,
    reviewPayload: (response.review_payload ??
      current.reviewPayload ??
      undefined) as Prisma.InputJsonValue,
    errors: response.errors as Prisma.InputJsonValue,
    confidence: confidence ?? current.confidence ?? null,
  };
}

/** How a run reads in the inbox. */
export function statusLabel(status: string | null): { text: string; color: string } {
  switch (status) {
    case "validated":
      return { text: "Validada", color: "green" };
    case AWAITING_REVIEW:
      return { text: "Esperando revisión", color: "gold" };
    case "needs_review":
      return { text: "Necesita revisión", color: "orange" };
    case "routing_budget_exhausted":
      return { text: "Presupuesto de enrutado agotado", color: "red" };
    default:
      return { text: status ?? "En curso", color: "default" };
  }
}
