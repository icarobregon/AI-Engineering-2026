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

import type { GraphEstimateResponse, GraphState, RunProgress } from "./estimator/contracts";
import { AWAITING_REVIEW, responseFromState, runUpdateFrom, statusLabel } from "./supervisor";

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

  it("la confianza del checkpoint llena el hueco de las ejecuciones que NO pausan", () => {
    // El fallo que esto arregla: la puerta humana dispara por DEBAJO del umbral,
    // así que `review_payload` sólo informaba de las ejecuciones malas. Las
    // buenas guardaban null y la columna enseñaba un guion habiendo un 0,86.
    expect(runUpdateFrom(respuesta(), {}, 0.858).confidence).toBe(0.858);
  });

  it("el payload manda sobre el checkpoint: es la foto que vio el revisor", () => {
    const fila = runUpdateFrom(respuesta({ review_payload: INFORME }), {}, 0.9);

    expect(fila.confidence).toBe(0.42);
  });

  it("el checkpoint manda sobre la fila, que sigue siendo el último recurso", () => {
    expect(runUpdateFrom(respuesta(), { confidence: 0.1 }, 0.858).confidence).toBe(0.858);
    // Sin checkpoint —el resume contesta sin payload— la fila conserva lo suyo.
    expect(runUpdateFrom(respuesta(), { confidence: 0.1 }).confidence).toBe(0.1);
  });

  it("un cero del checkpoint es un cero, no un hueco", () => {
    // `||` en vez de `??` aquí convertiría en «no lo sé» justo la señal que
    // hace que una estimación acabe delante de una persona.
    expect(runUpdateFrom(respuesta(), { confidence: 0.7 }, 0).confidence).toBe(0);
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

describe("responseFromState", () => {
  const progreso = (extra: Partial<RunProgress> = {}): RunProgress => ({
    estimation_id: "EST-1",
    status: "finished",
    current: null,
    failure: null,
    steps: [],
    counts: {
      requirements: 0,
      components: 0,
      budget_matches: 0,
      routing_steps: 0,
      has_estimate: true,
      confidence: null,
    },
    errors: [],
    routing_trail: [],
    last_activity_at: "2026-09-20T10:00:00+00:00",
    review_payload: null,
    ...extra,
  });

  const estado = (values: Record<string, unknown> = {}): GraphState =>
    ({
      estimation_id: "EST-1",
      next: [],
      values: {
        routing_trail: [],
        errors: [],
        ...values,
      },
    }) as GraphState;

  it("consolida la estimación y el estado final del checkpoint", () => {
    const respuesta = responseFromState(
      estado({
        status: "validated",
        estimate: { project: "RUTA", components: [], total_hours: 160, notes: "" },
      }),
      progreso(),
    );

    expect(respuesta.status).toBe("validated");
    expect(respuesta.estimate?.total_hours).toBe(160);
    expect(respuesta.estimation_id).toBe("EST-1");
  });

  it("en la pausa manda el sondeo, no el checkpoint", () => {
    // `status` lo escribe sólo `finalize`, así que un run parado ante una
    // persona todavía no lo tiene: leerlo del checkpoint daría «needs_review»
    // y la fila saldría de la bandeja sin que nadie decidiera nada.
    const respuesta = responseFromState(
      estado({ estimate: { project: "RUTA", components: [], total_hours: 160, notes: "" } }),
      progreso({ status: "awaiting_human_review", review_payload: INFORME }),
    );

    expect(respuesta.status).toBe(AWAITING_REVIEW);
    expect(respuesta.review_payload?.confidence).toBe(0.42);
  });

  it("un checkpoint sin status cae a needs_review, nunca a validated", () => {
    // El sesgo correcto: un run del que no sabemos el desenlace es uno que
    // alguien tiene que mirar.
    expect(responseFromState(estado(), progreso()).status).toBe("needs_review");
  });

  it("los errores vienen del sondeo, que ya filtró el marcador interno", () => {
    const respuesta = responseFromState(
      estado({ errors: ["algo viejo"] }),
      progreso({ errors: ["search_budgets(App móvil): RuntimeError"] }),
    );

    expect(respuesta.errors).toEqual(["search_budgets(App móvil): RuntimeError"]);
  });

  it("encaja con runUpdateFrom sin un segundo mapeo", () => {
    // La razón de existir de esta función: que siga habiendo UNA sola
    // correspondencia entre el contrato y la fila.
    const fila = runUpdateFrom(
      responseFromState(
        estado({
          status: "validated",
          estimate: { project: "RUTA", components: [], total_hours: 160, notes: "" },
        }),
        progreso(),
      ),
    );

    expect(fila.runState).toBe("completed");
    expect(fila.status).toBe("validated");
  });
});
