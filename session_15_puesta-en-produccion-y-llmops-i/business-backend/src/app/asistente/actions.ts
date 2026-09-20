"use server";

import { redirect } from "next/navigation";
import { ZodError } from "zod";
import { revalidatePath } from "next/cache";

import type { Prisma } from "@/generated/prisma/client";
import { prisma } from "@/lib/db";
import {
  estimationQuerySchema,
  estimateTreeSchema,
  taskHoursResultSchema,
  DEFAULT_RATE_EUR,
  type TaskHoursEstimate,
} from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import {
  MAX_TRANSCRIPT,
  MIN_TRANSCRIPT,
  estimateTaskHours,
  generateStructure,
  reformulate,
} from "@/lib/estimator/wizard";

export type FormState = { error: string | null; notice: string | null };

/**
 * Traduce un fallo a algo que se pueda leer en pantalla.
 *
 * El caso interesante es el de zod: su `.message` es un volcado JSON de todos
 * los problemas, y pintarlo crudo convierte «el contrato se movió» en un muro de
 * texto. Se resume a los campos que fallaron, que es lo accionable.
 */
function comoError(error: unknown, fallback: string): FormState {
  if (error instanceof EstimatorError) return { error: error.userMessage, notice: null };
  if (error instanceof ZodError) {
    const campos = [...new Set(error.issues.map((i) => i.path.join(".")))].slice(0, 5);
    return {
      error: `El servicio IA respondió con una forma que no esperábamos. Campos: ${campos.join(", ")}.`,
      notice: null,
    };
  }
  return { error: error instanceof Error ? error.message : fallback, notice: null };
}

/** El árbol tal y como lo edita una persona en el paso 3. */
type ModuloEditable = {
  name: string;
  description: string | null;
  tasks: { name: string; description: string | null }[];
};

/**
 * Lee el árbol del FormData.
 *
 * Los campos llegan como `modules[0][tasks][1][name]`. Los índices sólo tienen
 * que ser únicos: los huecos que dejan los borrados son legales, así que se
 * ordena por índice numérico en vez de asumir que son consecutivos.
 *
 * Lo que NO se hace es descartar en silencio las filas sin nombre. La app de
 * referencia las tira con un `filter_map`, así que una tarea con 99 h y 99 €/h a
 * la que se le olvidó el nombre desaparece sin decir nada.
 */
function leerArbol(formData: FormData): { modules: ModuloEditable[]; sinNombre: number } {
  const porModulo = new Map<number, ModuloEditable>();
  let sinNombre = 0;

  const indices = (clave: string) => {
    const m = clave.match(/^modules\[(\d+)\]\[tasks\]\[(\d+)\]\[(\w+)\]$/);
    if (m) return { modulo: Number(m[1]), tarea: Number(m[2]), campo: m[3] };
    const n = clave.match(/^modules\[(\d+)\]\[(\w+)\]$/);
    if (n) return { modulo: Number(n[1]), tarea: null, campo: n[2] };
    return null;
  };

  const tareas = new Map<number, Map<number, { name: string; description: string | null }>>();

  for (const [clave, valor] of formData.entries()) {
    const ref = indices(clave);
    if (!ref) continue;
    const texto = String(valor).trim();

    if (ref.tarea === null) {
      const modulo = porModulo.get(ref.modulo) ?? { name: "", description: null, tasks: [] };
      if (ref.campo === "name") modulo.name = texto;
      if (ref.campo === "description") modulo.description = texto || null;
      porModulo.set(ref.modulo, modulo);
    } else {
      const delModulo = tareas.get(ref.modulo) ?? new Map();
      const tarea = delModulo.get(ref.tarea) ?? { name: "", description: null };
      if (ref.campo === "name") tarea.name = texto;
      if (ref.campo === "description") tarea.description = texto || null;
      delModulo.set(ref.tarea, tarea);
      tareas.set(ref.modulo, delModulo);
    }
  }

  const modules: ModuloEditable[] = [];
  for (const [indice, modulo] of [...porModulo.entries()].sort((a, b) => a[0] - b[0])) {
    const suyas = [...(tareas.get(indice)?.entries() ?? [])].sort((a, b) => a[0] - b[0]);
    const conNombre = suyas.map(([, t]) => t).filter((t) => t.name.length > 0);
    sinNombre += suyas.length - conNombre.length;
    if (modulo.name.length === 0) {
      sinNombre += 1;
      continue;
    }
    modules.push({ ...modulo, tasks: conNombre });
  }

  return { modules, sinNombre };
}

// ---------------------------------------------------------------------------
// Paso 1 — crear y reformular
// ---------------------------------------------------------------------------

export async function createRun(_previous: FormState, formData: FormData): Promise<FormState> {
  const transcript = String(formData.get("transcript") ?? "").trim();
  if (transcript.length < MIN_TRANSCRIPT) {
    return {
      error: `La transcripción necesita al menos ${MIN_TRANSCRIPT} caracteres; tiene ${transcript.length}.`,
      notice: null,
    };
  }
  if (transcript.length > MAX_TRANSCRIPT) {
    return {
      error: `La transcripción no puede pasar de ${MAX_TRANSCRIPT.toLocaleString("es-ES")} caracteres; tiene ${transcript.length.toLocaleString("es-ES")}.`,
      notice: null,
    };
  }

  let brief;
  try {
    brief = await reformulate(transcript);
  } catch (error) {
    return comoError(error, "La reformulación falló.");
  }

  const run = await prisma.ragRun.create({
    data: { transcript, reformulation: brief, currentStep: "reformulation" },
  });
  redirect(`/asistente/${run.id}`);
}

/** Re-ejecutar la reformulación invalida todo lo que venía detrás. */
export async function rerunReformulation(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const runId = String(formData.get("run_id") ?? "");
  const run = await prisma.ragRun.findUnique({ where: { id: runId } });
  if (!run) return { error: "Esa ejecución ya no existe.", notice: null };

  let brief;
  try {
    brief = await reformulate(run.transcript);
  } catch (error) {
    return comoError(error, "La reformulación falló.");
  }

  await prisma.ragRun.update({
    where: { id: runId },
    data: {
      reformulation: brief,
      // En cascada y a propósito: un brief distinto deja sin sentido el árbol,
      // las horas y la confirmación que salieron del anterior.
      structure: undefined,
      reviewedModules: undefined,
      taskHours: undefined,
      verification: undefined,
      confirmedAt: null,
      currentStep: "reformulation",
    },
  });
  revalidatePath(`/asistente/${runId}`);
  return { error: null, notice: "Reformulación actualizada. Los pasos siguientes se han vaciado." };
}

// ---------------------------------------------------------------------------
// Paso 2 — estructura
// ---------------------------------------------------------------------------

export async function generateStructureFor(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const runId = String(formData.get("run_id") ?? "");
  const run = await prisma.ragRun.findUnique({ where: { id: runId } });
  if (!run?.reformulation) return { error: "Primero hace falta la reformulación.", notice: null };

  const query = estimationQuerySchema.safeParse(
    (run.reformulation as { query?: unknown }).query,
  );
  if (!query.success) return { error: "El brief guardado no tiene la forma esperada.", notice: null };

  let estructura;
  try {
    estructura = await generateStructure(query.data);
  } catch (error) {
    return comoError(error, "La generación de la estructura falló.");
  }

  await prisma.ragRun.update({
    where: { id: runId },
    data: {
      structure: estructura as Prisma.InputJsonValue,
      // El árbol revisado nace como copia del propuesto: el paso 3 edita sobre
      // él, y así se conserva el original para poder compararlos.
      reviewedModules: estructura.estimate.modules,
      taskHours: undefined,
      verification: undefined,
      confirmedAt: null,
      currentStep: "structure",
    },
  });
  revalidatePath(`/asistente/${runId}`);
  return { error: null, notice: "Estructura generada." };
}

// ---------------------------------------------------------------------------
// Paso 3 — revisión humana del árbol
// ---------------------------------------------------------------------------

export async function saveReview(_previous: FormState, formData: FormData): Promise<FormState> {
  const runId = String(formData.get("run_id") ?? "");
  const { modules, sinNombre } = leerArbol(formData);

  if (modules.length === 0) {
    return { error: "Deja al menos un módulo con nombre.", notice: null };
  }

  await prisma.ragRun.update({
    where: { id: runId },
    data: { reviewedModules: modules, currentStep: "review" },
  });
  revalidatePath(`/asistente/${runId}`);
  return {
    error: null,
    notice:
      sinNombre > 0
        ? `Árbol guardado. Se descartaron ${sinNombre} filas sin nombre.`
        : "Árbol guardado.",
  };
}

// ---------------------------------------------------------------------------
// Paso 4 — horas por tarea
// ---------------------------------------------------------------------------

export async function estimateHoursFor(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const runId = String(formData.get("run_id") ?? "");
  const run = await prisma.ragRun.findUnique({ where: { id: runId } });
  const modules = leerArbolGuardado(run?.reviewedModules);
  if (modules.length === 0) {
    return { error: "Primero hay que revisar la estructura.", notice: null };
  }
  if (modules.every((m) => m.tasks.length === 0)) {
    return { error: "Ningún módulo tiene tareas: no hay nada que estimar.", notice: null };
  }

  let horas;
  try {
    horas = await estimateTaskHours(modules);
  } catch (error) {
    return comoError(error, "La estimación de horas falló.");
  }

  await prisma.ragRun.update({
    where: { id: runId },
    data: { taskHours: horas, verification: undefined, confirmedAt: null, currentStep: "hours" },
  });
  revalidatePath(`/asistente/${runId}`);
  const sinDato = horas.tasks.filter((t) => !t.has_match).length;
  return {
    error: null,
    notice:
      sinDato > 0
        ? `Horas estimadas. ${sinDato} tareas sin analogía en el corpus: las horas las pones tú.`
        : "Horas estimadas desde el corpus histórico.",
  };
}

/** Lee el árbol revisado de la columna JSONB, tolerando que aún no exista. */
function leerArbolGuardado(value: unknown): ModuloEditable[] {
  const parsed = estimateTreeSchema.shape.modules.safeParse(value);
  if (!parsed.success) return [];
  return parsed.data.map((m) => ({
    name: m.name,
    description: m.description,
    tasks: m.tasks.map((t) => ({ name: t.name, description: t.description })),
  }));
}

// ---------------------------------------------------------------------------
// Paso 5 — verificación y confirmación
// ---------------------------------------------------------------------------

export async function confirmEstimate(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const runId = String(formData.get("run_id") ?? "");
  const run = await prisma.ragRun.findUnique({ where: { id: runId } });
  if (!run) return { error: "Esa ejecución ya no existe.", notice: null };

  const horas = taskHoursResultSchema.safeParse(run.taskHours);
  const porTarea = new Map<string, TaskHoursEstimate>();
  if (horas.success) {
    horas.data.tasks.forEach((t, i) => porTarea.set(String(i), t));
  }

  const { modules } = leerArbol(formData);
  const lineas: {
    module: string;
    task: string;
    hours: number;
    rate: number;
    cost: number;
    reliability: number | null;
    hadMatch: boolean;
  }[] = [];

  let indice = 0;
  for (const modulo of modules) {
    for (const tarea of modulo.tasks) {
      const clave = `t${indice}`;
      // El total que calculó el navegador viaja pero NO se usa: aquí se
      // recalcula tarea a tarea, que es la única cifra que puede defenderse.
      const h = Number(formData.get(`hours[${clave}]`) ?? 0);
      const r = Number(formData.get(`rate[${clave}]`) ?? DEFAULT_RATE_EUR);
      const original = porTarea.get(String(indice));
      lineas.push({
        module: modulo.name,
        task: tarea.name,
        hours: Number.isFinite(h) && h > 0 ? Math.round(h) : 0,
        rate: Number.isFinite(r) && r > 0 ? Math.round(r) : 0,
        cost: 0,
        // Se conservan: la app de referencia los tira al confirmar y con ellos
        // desaparece la única señal de qué números venían flojos.
        reliability: original?.reliability ?? null,
        hadMatch: original?.has_match ?? false,
      });
      indice += 1;
    }
  }

  for (const linea of lineas) linea.cost = linea.hours * linea.rate;

  const totalHoras = lineas.reduce((n, l) => n + l.hours, 0);
  const totalCoste = lineas.reduce((n, l) => n + l.cost, 0);

  if (lineas.length === 0) {
    return { error: "No hay ninguna línea que confirmar.", notice: null };
  }

  await prisma.ragRun.update({
    where: { id: runId },
    data: {
      verification: { lines: lineas, totalHours: totalHoras, totalCostEur: totalCoste },
      confirmedAt: new Date(),
      currentStep: "verification",
    },
  });
  revalidatePath(`/asistente/${runId}`);
  return {
    error: null,
    notice: `Estimación confirmada: ${totalHoras} h · ${totalCoste.toLocaleString("es-ES")} €.`,
  };
}
