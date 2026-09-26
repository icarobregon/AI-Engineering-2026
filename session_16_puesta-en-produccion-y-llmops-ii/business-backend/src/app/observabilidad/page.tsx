import { EstimatorError } from "@/lib/estimator/errors";
import { getMetricsSummary } from "@/lib/estimator/metrics";
import type { MetricsSummary } from "@/lib/estimator/contracts";
import { ObservabilidadView } from "./observabilidad-view";

export const dynamic = "force-dynamic";

export const metadata = { title: "Observabilidad" };

export default async function ObservabilidadPage() {
  let summary: MetricsSummary | null = null;
  let error: string | null = null;
  try {
    summary = await getMetricsSummary("24h");
  } catch (e) {
    // El panel mide al servicio IA, así que si el servicio IA no está, el panel
    // no tiene nada que enseñar — y decirlo es más útil que una pantalla vacía.
    error =
      e instanceof EstimatorError
        ? e.userMessage
        : "No se pudieron leer las métricas del servicio.";
  }

  return <ObservabilidadView initial={summary} initialError={error} />;
}
