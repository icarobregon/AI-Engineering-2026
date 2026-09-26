/** Sesiones 09–12 — las tres etapas que el asistente RAG encadena. */
import "server-only";

import { callEstimator } from "./client";
import {
  reformulationSchema,
  structureResultSchema,
  taskHoursResultSchema,
  type EstimationQuery,
  type Reformulation,
  type StructureResult,
  type TaskHoursResult,
} from "./contracts";

/** El servicio exige al menos 100 caracteres; decirlo antes evita un 422 opaco. */
export const MIN_TRANSCRIPT = 100;
export const MAX_TRANSCRIPT = 50_000;

/**
 * Paso 1 — la transcripción, llena de ruido, se convierte en un brief tipado.
 *
 * `search_text` es el texto alineado con el corpus que alimentaría al embebedor.
 * En este flujo no se usa para recuperar nada todavía: el retrieval entra por
 * tarea, en el paso de horas.
 */
export async function reformulate(transcript: string): Promise<Reformulation> {
  const payload = await callEstimator<unknown>("/v1/estimate/stages/reformulate", {
    method: "POST",
    body: { transcript },
  });
  return reformulationSchema.parse(payload);
}

/**
 * Paso 2 — el brief se descompone en módulos y tareas, SIN mirar el corpus.
 *
 * Es deliberado y es lo que cambió en la S10: generar la estructura con
 * presupuestos recuperados delante empobrecía el árbol, porque el modelo se
 * ceñía a lo que ya existía. Aquí no viaja ningún `context_block`, y por eso el
 * resultado llega sin citas, sin `grounded` y sin días por tarea.
 *
 * **Es la llamada más lenta del sistema**: `gpt-5` con `reasoning_effort=high` y
 * 64.000 tokens de presupuesto, donde los de razonamiento cuentan. Medido contra
 * una transcripción de 700 caracteres, pasa de los cinco minutos. Los 300 s que
 * usa la app de referencia se quedan cortos y cortan una respuesta que el
 * servicio sí acaba devolviendo — pagada y tirada.
 */
export async function generateStructure(query: EstimationQuery): Promise<StructureResult> {
  const payload = await callEstimator<unknown>("/v1/estimate/stages/structure", {
    method: "POST",
    timeoutMs: 900_000,
    body: { query },
  });
  return structureResultSchema.parse(payload);
}

/**
 * Paso 4 — las horas, tarea a tarea, por consenso con el corpus histórico.
 *
 * El servicio devuelve las tareas EN EL MISMO ORDEN en que se enviaron, que es
 * lo que permite emparejarlas por posición. La app de referencia empareja por
 * (nombre de módulo, nombre de tarea) y eso se rompe en cuanto alguien renombra
 * algo entre pasos, o cuando dos tareas del mismo módulo se llaman igual.
 */
export async function estimateTaskHours(
  modules: { name: string; tasks: { name: string; description: string | null }[] }[],
): Promise<TaskHoursResult> {
  const payload = await callEstimator<unknown>("/v1/estimate/tasks/hours", {
    method: "POST",
    timeoutMs: 300_000,
    body: {
      modules: modules.map((m) => ({
        name: m.name,
        tasks: m.tasks.map((t) => ({ name: t.name, description: t.description })),
      })),
    },
  });
  return taskHoursResultSchema.parse(payload);
}
