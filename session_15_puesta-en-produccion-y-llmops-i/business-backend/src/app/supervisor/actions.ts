"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { prisma } from "@/lib/db";
import {
  humanDecisionSchema,
  reviewPayloadSchema,
  type RunProgress,
} from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import {
  draftCommercialProposal,
  getSupervisedRunProgress,
  getSupervisedRunState,
  launchSupervisedEstimation,
  resumeSupervisedEstimation,
} from "@/lib/estimator/graph";
import { FAILED, responseFromState, runUpdateFrom } from "@/lib/supervisor";
import { componentesSinPrecio, parseComponentHours } from "./review";

export type FormState = { error: string | null };

export async function startRun(_previous: FormState, formData: FormData): Promise<FormState> {
  const transcript = String(formData.get("transcript") ?? "").trim();
  if (transcript.length < 100) {
    return { error: "La transcripción necesita al menos 100 caracteres para ser estimable." };
  }

  // Our id, not one the AI service invents: it is the thread_id of the run, the
  // key of our row and what a reviewer quotes days later. Generating it here is
  // what makes a retry land on the same run instead of starting a second one.
  const estimationId = randomUUID();

  let id: string;
  try {
    const run = await prisma.supervisorRun.create({
      data: { estimationId, transcript, runState: "running" },
    });
    id = run.id;

    // Session 15: this returns as soon as the service accepts the work, not
    // when the work is done. The row stays `running` and the screen polls it —
    // which is what stopped this action's own timeout from being a ceiling on
    // how long an estimation is allowed to take.
    await launchSupervisedEstimation(transcript, estimationId);
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage };
    throw error;
  }

  redirect(`/supervisor/${id}`);
}

export type SyncResult = { progress: RunProgress | null; error: string | null };

/**
 * One poll: read the progress and, when the run has settled, fold the result
 * into our row.
 *
 * A Server Action and not a route handler on purpose. This writes, and a GET
 * that writes to the database is precisely the shape worth not copying from the
 * reference implementation — there, the polling endpoint persists the run state
 * as a side effect, so a crawler or a prefetch mutates a row.
 */
export async function syncRun(id: string): Promise<SyncResult> {
  const run = await prisma.supervisorRun.findUnique({
    where: { id },
    select: { id: true, estimationId: true, estimate: true, reviewPayload: true, confidence: true },
  });
  if (!run) return { progress: null, error: "Esa ejecución ya no existe." };

  let progress: RunProgress;
  try {
    progress = await getSupervisedRunProgress(run.estimationId);
  } catch (error) {
    // A failed poll is not a failed run: the network blinked, or the service is
    // restarting while the graph's own state sits safely in the checkpointer.
    // Reporting it as a dead run would be worse than saying nothing.
    if (error instanceof EstimatorError) return { progress: null, error: error.userMessage };
    throw error;
  }

  if (progress.status === "running") return { progress, error: null };

  if (progress.status === "failed") {
    await prisma.supervisorRun.update({
      where: { id },
      data: {
        runState: FAILED,
        status: FAILED,
        errors: [...progress.errors, progress.failure ?? "La ejecución murió sin decir por qué."],
      },
    });
    revalidatePath(`/supervisor/${id}`);
    return { progress, error: null };
  }

  // Settled: the estimate and the final status live in the checkpoint, which is
  // read with the verb meant for reading rather than carried on every poll.
  const state = await getSupervisedRunState(run.estimationId);
  await prisma.supervisorRun.update({
    where: { id },
    data: runUpdateFrom(responseFromState(state, progress), run, {
      confidence: state.values.confidence,
      budgetMatches: state.values.budget_matches,
    }),
  });
  revalidatePath(`/supervisor/${id}`);
  revalidatePath("/supervisor");
  return { progress, error: null };
}

export async function submitReview(_previous: FormState, formData: FormData): Promise<FormState> {
  const id = String(formData.get("id") ?? "");
  const accion = String(formData.get("action") ?? "");
  const revisor = String(formData.get("reviewer_id") ?? "").trim();
  const motivo = String(formData.get("comment") ?? "").trim();

  if (accion !== "approve" && accion !== "reject") {
    return { error: "Decisión inválida: sólo se puede aprobar o rechazar." };
  }
  // Se comprueba aquí ADEMÁS de deshabilitar el botón. Lo de la pantalla es
  // cortesía; esto es la regla, y es lo único que sigue en pie si alguien llama
  // a la acción desde fuera del formulario.
  if (!revisor || !motivo) {
    return { error: "Revisor y Motivo son obligatorios para aprobar o rechazar." };
  }

  let componentHours: Record<string, number>;
  try {
    componentHours = parseComponentHours(formData.get("component_hours"));
  } catch (error) {
    return { error: error instanceof Error ? error.message : "Horas inválidas." };
  }

  const run = await prisma.supervisorRun.findUnique({ where: { id } });
  if (!run) return { error: "Esa estimación ya no existe." };

  // Los componentes se leen de lo GUARDADO, no de lo que mandó el formulario:
  // uno omitido entero no se puede echar de menos mirando sólo lo que llegó.
  const briefing = reviewPayloadSchema.safeParse(run.reviewPayload);
  const componentes = briefing.success ? (briefing.data.estimate?.components ?? []) : [];
  if (accion === "approve") {
    const sinPrecio = componentesSinPrecio(componentes, componentHours);
    if (sinPrecio.length > 0) {
      return {
        error: `No se puede aprobar con componentes a 0 h: ${sinPrecio.join(", ")}.`,
      };
    }
  }

  const parsed = humanDecisionSchema.safeParse({
    action: accion,
    component_hours: componentHours,
    comment: motivo,
    reviewer_id: revisor,
  });
  if (!parsed.success) return { error: "Decisión inválida." };

  try {
    const response = await resumeSupervisedEstimation(run.estimationId, parsed.data);
    await prisma.supervisorRun.update({
      where: { id },
      data: {
        ...runUpdateFrom(response, run),
        // Kept on our side on purpose: who decided and why is business history,
        // and the AI service has no business owning it.
        humanDecision: { ...parsed.data, decided_at: new Date().toISOString() },
      },
    });
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage };
    throw error;
  }

  revalidatePath(`/supervisor/${id}`);
  revalidatePath("/supervisor");
  return { error: null };
}

/**
 * Draft — or redraft — the commercial proposal.
 *
 * Redrafting is a first-class outcome, not a retry: the numbers are settled and
 * only the prose is regenerated, so a proposal whose tone missed costs one
 * generation rather than a whole estimation. The previous draft is overwritten
 * because nothing here reads an older one; keeping a history would be a feature
 * nobody asked for.
 */
export async function generateProposal(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const id = String(formData.get("id") ?? "");
  const run = await prisma.supervisorRun.findUnique({
    where: { id },
    select: { id: true, estimationId: true },
  });
  if (!run) return { error: "Esa estimación ya no existe." };

  try {
    const proposal = await draftCommercialProposal(run.estimationId);
    await prisma.supervisorRun.update({ where: { id }, data: { proposal } });
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage };
    throw error;
  }

  revalidatePath(`/supervisor/${id}`);
  return { error: null };
}
