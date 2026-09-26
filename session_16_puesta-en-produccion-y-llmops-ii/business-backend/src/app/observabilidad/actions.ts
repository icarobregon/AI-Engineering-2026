"use server";

import { EstimatorError } from "@/lib/estimator/errors";
import { getMetricsSummary } from "@/lib/estimator/metrics";
import type { MetricsSummary, MetricsWindow } from "@/lib/estimator/contracts";

export type MetricsResult = { summary: MetricsSummary | null; error: string | null };

/**
 * Una lectura del panel.
 *
 * Server Action y no route handler, por lo mismo que el resto de la aplicación:
 * la clave del servicio IA no sale de este proceso, y la frontera público /
 * privado de la S15 dice que el servicio sólo se alcanza desde aquí. Un route
 * handler abriría una ruta pública que devuelve lo que cuesta operar el
 * sistema.
 *
 * Devuelve un resultado en vez de lanzar: si el servicio IA está reiniciando,
 * la pantalla tiene que poder decirlo y seguir enseñando lo que ya tenía, no
 * romperse entera.
 */
export async function leerMetricas(window: MetricsWindow): Promise<MetricsResult> {
  try {
    return { summary: await getMetricsSummary(window), error: null };
  } catch (error) {
    if (error instanceof EstimatorError) return { summary: null, error: error.userMessage };
    throw error;
  }
}
