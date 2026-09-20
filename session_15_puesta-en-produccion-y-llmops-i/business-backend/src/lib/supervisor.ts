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
import type { GraphEstimateResponse, GraphState, RunProgress } from "@/lib/estimator/contracts";
import type { Prisma } from "@/generated/prisma/client";

export const AWAITING_REVIEW = "awaiting_human_review";
/** No es un estado del servicio IA: es el nuestro para un run que murió. */
export const FAILED = "failed";

type Current = {
  estimate?: Prisma.JsonValue | null;
  reviewPayload?: Prisma.JsonValue | null;
  confidence?: number | null;
};

export function runUpdateFrom(
  response: GraphEstimateResponse,
  current: Current = {},
  /**
   * La confianza leída del checkpoint, para quien la tenga a mano.
   *
   * El contrato HTTP no la lleva: `GraphEstimateResponse` no tiene ese campo y
   * sólo aparece colada dentro de `review_payload`, que existe únicamente cuando
   * dispara la puerta humana. Y la puerta dispara por DEBAJO del umbral, así que
   * esa vía sólo informaba de las ejecuciones que no se ganan la confianza: las
   * buenas guardaban null y la columna enseñaba un guion habiendo un 0,86.
   */
  fromState?: number | null,
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
    // El orden no es cosmético. El payload manda porque es la foto que vio el
    // revisor; el checkpoint va después; y la fila sigue siendo el último
    // recurso, porque el resume contesta SIN payload y sin ese fallback aprobar
    // una estimación le borraría la confianza. Todo con `??` y nunca con `||`:
    // un 0 es un valor legítimo —es justo el que dispara la puerta— y `||` lo
    // convertiría en el guion que significa «no lo sé».
    confidence: confidence ?? fromState ?? current.confidence ?? null,
  };
}

/**
 * El resultado de un run arrancado en segundo plano, con la forma que ya sabe
 * persistir `runUpdateFrom`.
 *
 * Existe para que siga habiendo UNA sola correspondencia entre el contrato y la
 * fila. Desde la S15 el resultado puede llegar por dos caminos —la respuesta del
 * arranque bloqueante, o el checkpoint leído después de sondear— y escribir un
 * segundo mapeo es cómo la forma persistida empieza a divergir del contrato.
 */
export function responseFromState(state: GraphState, progress: RunProgress): GraphEstimateResponse {
  return {
    estimate: state.values.estimate ?? null,
    // El sondeo manda sobre el checkpoint en la pausa: `status` sólo lo escribe
    // `finalize`, así que un run parado ante una persona no lo tiene todavía.
    status:
      progress.status === AWAITING_REVIEW
        ? AWAITING_REVIEW
        : (state.values.status ?? "needs_review"),
    estimation_id: state.estimation_id,
    errors: progress.errors,
    review_payload: progress.review_payload ?? null,
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
    case FAILED:
      return { text: "Falló", color: "red" };
    default:
      return { text: status ?? "En curso", color: "default" };
  }
}
