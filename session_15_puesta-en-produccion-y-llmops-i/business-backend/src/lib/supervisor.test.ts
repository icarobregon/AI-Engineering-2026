/**
 * El mapeo de respuesta a fila del supervisor.
 *
 * Es el sitio de esta capa donde un fallo se lleva por delante trabajo humano:
 * las ramas idempotentes del router de Python contestan SIN `review_payload`, y
 * un mapeo que sobrescribiera a ciegas borraría el informe del revisor en cuanto
 * alguien recargara la página. Los `?? current` parecen ruido defensivo y no lo
 * son; esto es lo que impide que alguien los quite por parecerlo.
 */

import { describe, expect, it } from "vitest";

import type { GraphEstimateResponse } from "./estimator/contracts";
import { AWAITING_REVIEW, runUpdateFrom, statusLabel } from "./supervisor";

const INFORME = {
  confidence: 0.42,
  triggers: ["low_confidence"],
  concerns: ["Sin precedentes para el módulo de visión"],
} as unknown as GraphEstimateResponse["review_payload"];

function respuesta(extra: Partial<GraphEstimateResponse> = {}): GraphEstimateResponse {
  return {
    estimation_id: "run-1",
    status: "validated",
    errors: [],
    ...extra,
  } as GraphEstimateResponse;
}

describe("runUpdateFrom", () => {
  it("una pausa deja la fila en paused y una respuesta normal en completed", () => {
    expect(runUpdateFrom(respuesta({ status: AWAITING_REVIEW })).runState).toBe("paused");
    expect(runUpdateFrom(respuesta({ status: "validated" })).runState).toBe("completed");
  });

  it("recoge el informe y la confianza cuando la respuesta los trae", () => {
    const fila = runUpdateFrom(
      respuesta({ status: AWAITING_REVIEW, review_payload: INFORME, estimate: { a: 1 } as never }),
    );

    expect(fila.reviewPayload).toEqual(INFORME);
    expect(fila.confidence).toBe(0.42);
  });

  it("NO borra el informe del revisor cuando la respuesta no lo trae", () => {
    // El caso que rompe de verdad: el router contesta idempotente, sin
    // review_payload, y quien estaba leyendo el informe lo pierde al recargar.
    const fila = runUpdateFrom(respuesta({ status: AWAITING_REVIEW }), {
      reviewPayload: INFORME as never,
      estimate: { a: 1 } as never,
      confidence: 0.42,
    });

    expect(fila.reviewPayload).toEqual(INFORME);
    expect(fila.estimate).toEqual({ a: 1 });
    expect(fila.confidence).toBe(0.42);
  });

  it("un valor nuevo sí sustituye al anterior", () => {
    const nuevo = { ...(INFORME as object), confidence: 0.88 } as typeof INFORME;
    const fila = runUpdateFrom(respuesta({ review_payload: nuevo }), { confidence: 0.42 });

    expect(fila.confidence).toBe(0.88);
  });

  it("sin confianza por ninguna parte, null y no undefined", () => {
    // `undefined` en Prisma significa «no toques esta columna»; `null` significa
    // «ponla a null». Aquí queremos lo segundo.
    expect(runUpdateFrom(respuesta()).confidence).toBeNull();
  });
});

describe("statusLabel", () => {
  it("traduce los cuatro estados que el servicio IA emite", () => {
    expect(statusLabel("validated").text).toBe("Validada");
    expect(statusLabel(AWAITING_REVIEW).color).toBe("gold");
    expect(statusLabel("needs_review").color).toBe("orange");
    expect(statusLabel("routing_budget_exhausted").color).toBe("red");
  });

  it("un estado desconocido se enseña crudo en vez de ocultarse", () => {
    // Inventarse una traducción escondería que el contrato se movió.
    expect(statusLabel("paused_for_aliens").text).toBe("paused_for_aliens");
    expect(statusLabel(null).text).toBe("En curso");
  });
});
