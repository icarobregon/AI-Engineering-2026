/** Sesión 16 — las constantes vitales del servicio IA, ya agregadas por él. */
import "server-only";

import { callEstimator } from "./client";
import { metricsSummarySchema, type MetricsSummary, type MetricsWindow } from "./contracts";

/**
 * Latencia, coste y tasa de error del tráfico real sobre una ventana.
 *
 * Es la otra mitad de la Sesión 16: el golden set mide la calidad cuando se
 * lanza la evaluación, con entradas elegidas; esto mide lo que el sistema hace
 * el resto del tiempo, con las entradas que manda el mundo.
 */
export async function getMetricsSummary(window: MetricsWindow = "24h"): Promise<MetricsSummary> {
  const payload = await callEstimator<unknown>(`/v1/metrics/summary?window=${window}`, {
    timeoutMs: 15_000,
  });
  return metricsSummarySchema.parse(payload);
}
