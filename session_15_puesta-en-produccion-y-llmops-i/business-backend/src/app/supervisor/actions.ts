"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { prisma } from "@/lib/db";
import { humanDecisionSchema } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { resumeSupervisedEstimation, startSupervisedEstimation } from "@/lib/estimator/graph";
import { runUpdateFrom } from "@/lib/supervisor";

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

    const response = await startSupervisedEstimation(transcript, estimationId);
    await prisma.supervisorRun.update({
      where: { id },
      data: runUpdateFrom(response),
    });
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage };
    throw error;
  }

  redirect(`/supervisor/${id}`);
}

export async function submitReview(_previous: FormState, formData: FormData): Promise<FormState> {
  const id = String(formData.get("id") ?? "");
  const rawHours = formData.get("adjusted_hours");

  const parsed = humanDecisionSchema.safeParse({
    action: formData.get("action"),
    adjusted_hours: rawHours ? Number(rawHours) : null,
    comment: formData.get("comment") || null,
    reviewer_id: formData.get("reviewer_id") || null,
  });
  if (!parsed.success) return { error: "Decisión inválida: elige aprobar, ajustar o rechazar." };
  if (parsed.data.action === "adjust" && parsed.data.adjusted_hours == null) {
    return { error: "Para ajustar hay que indicar el total de horas." };
  }

  const run = await prisma.supervisorRun.findUnique({ where: { id } });
  if (!run) return { error: "Esa estimación ya no existe." };

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
