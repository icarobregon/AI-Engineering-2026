"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import type { Prisma } from "@/generated/prisma/client";
import { prisma } from "@/lib/db";
import { reasoningEfforts, type ReasoningEffort } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { runAgent } from "@/lib/estimator/agent";

export type FormState = { error: string | null; notice: string | null };

/** El servicio exige 100 caracteres; decirlo antes evita un 422 opaco. */
const MIN_TRANSCRIPT = 100;

/** Sin señales durante esto, un run se da por colgado. El bucle es largo. */
const SIN_SEÑALES_MS = 10 * 60_000;

function textoONulo(formData: FormData, campo: string): string | null {
  const valor = String(formData.get(campo) ?? "").trim();
  return valor.length > 0 ? valor : null;
}

// ---------------------------------------------------------------------------
// Perfiles
// ---------------------------------------------------------------------------

/**
 * Sólo puede haber un perfil por defecto.
 *
 * Se resuelve en una transacción, no con dos updates sueltos: si el segundo
 * fallara, quedarían dos por defecto y la consola preseleccionaría uno al azar.
 */
async function marcarComoUnico(profileId: string) {
  await prisma.$transaction([
    prisma.agentProfile.updateMany({
      where: { id: { not: profileId } },
      data: { isDefault: false },
    }),
    prisma.agentProfile.update({ where: { id: profileId }, data: { isDefault: true } }),
  ]);
}

function leerPerfil(formData: FormData) {
  const name = String(formData.get("name") ?? "").trim();
  const rawEffort = String(formData.get("reasoning_effort") ?? "");
  const rawIterations = String(formData.get("max_iterations") ?? "").trim();
  const iterations = rawIterations.length > 0 ? Number(rawIterations) : null;

  return {
    name,
    description: textoONulo(formData, "description"),
    model: textoONulo(formData, "model"),
    reasoningEffort: (reasoningEfforts as readonly string[]).includes(rawEffort)
      ? (rawEffort as ReasoningEffort)
      : null,
    maxIterations:
      iterations !== null && Number.isFinite(iterations) && iterations > 0
        ? Math.min(30, Math.round(iterations))
        : null,
    isDefault: formData.get("is_default") === "on",
  };
}

export async function saveProfile(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const id = String(formData.get("id") ?? "");
  const datos = leerPerfil(formData);

  if (datos.name.length === 0) {
    return { error: "El perfil necesita un nombre.", notice: null };
  }

  const { isDefault, ...campos } = datos;
  const perfil = id
    ? await prisma.agentProfile.update({ where: { id }, data: campos })
    : await prisma.agentProfile.create({ data: campos });

  if (isDefault) await marcarComoUnico(perfil.id);
  else if (id) await prisma.agentProfile.update({ where: { id }, data: { isDefault: false } });

  revalidatePath("/agentes");
  redirect("/agentes");
}

export async function deleteProfile(formData: FormData): Promise<void> {
  const id = String(formData.get("id") ?? "");
  // Las ejecuciones NO se borran con el perfil: `onDelete: SetNull`. Cada una
  // guardó los ajustes con los que corrió, así que sigue explicándose sola.
  await prisma.agentProfile.delete({ where: { id } });
  revalidatePath("/agentes");
}

// ---------------------------------------------------------------------------
// Ejecuciones
// ---------------------------------------------------------------------------

/**
 * Corre el agente en segundo plano y va dejando el resultado en la fila.
 *
 * Sin `await` desde la acción, igual que la ampliación del corpus: el bucle
 * tarda minutos y la persona va al detalle a ver el progreso. Un reinicio del
 * proceso a mitad deja la fila en `running` sin nadie que la mueva, y por eso el
 * detalle detecta un run sin señales en vez de fingir que sigue vivo.
 */
async function ejecutar(runId: string, transcript: string, ajustes: {
  model: string | null;
  reasoningEffort: string | null;
  maxIterations: number | null;
}) {
  await prisma.agentRun.update({
    where: { id: runId },
    data: { status: "running", startedAt: new Date() },
  });

  try {
    const respuesta = await runAgent({ transcript, ...ajustes });
    await prisma.agentRun.update({
      where: { id: runId },
      data: {
        status: "completed",
        estimate: respuesta.estimate as Prisma.InputJsonValue,
        trace: respuesta.trace as Prisma.InputJsonValue,
        finishedAt: new Date(),
      },
    });
  } catch (error) {
    await prisma.agentRun.update({
      where: { id: runId },
      data: {
        status: "failed",
        errorMessage:
          error instanceof EstimatorError
            ? error.userMessage
            : error instanceof Error
              ? error.message
              : "El agente falló por un motivo desconocido.",
        finishedAt: new Date(),
      },
    });
  }
}

export async function startAgentRun(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
  const transcript = String(formData.get("transcript") ?? "").trim();
  if (transcript.length < MIN_TRANSCRIPT) {
    return {
      error: `La transcripción necesita al menos ${MIN_TRANSCRIPT} caracteres; tiene ${transcript.length}.`,
      notice: null,
    };
  }

  const profileId = String(formData.get("profile_id") ?? "");
  const perfil = profileId
    ? await prisma.agentProfile.findUnique({ where: { id: profileId } })
    : null;
  if (profileId && !perfil) {
    return { error: "Ese perfil ya no existe.", notice: null };
  }

  const ajustes = {
    model: perfil?.model ?? null,
    reasoningEffort: perfil?.reasoningEffort ?? null,
    maxIterations: perfil?.maxIterations ?? null,
  };

  const run = await prisma.agentRun.create({
    data: {
      profileId: perfil?.id ?? null,
      transcript,
      // Copiados, no referenciados: el perfil puede cambiar o borrarse después y
      // esta ejecución tiene que seguir diciendo con qué corrió. Lo que quedó a
      // null lo resolvió el .env del servicio, y eso se dice en pantalla.
      model: ajustes.model ?? "(por defecto del servicio)",
      reasoningEffort: ajustes.reasoningEffort ?? "(por defecto del servicio)",
      maxIterations: ajustes.maxIterations ?? 0,
    },
  });

  void ejecutar(run.id, transcript, ajustes);

  redirect(`/agentes/ejecuciones/${run.id}`);
}

/** Lo que consulta el sondeo. Sólo LEE. */
export async function pollAgentRun(runId: string) {
  const run = await prisma.agentRun.findUnique({
    where: { id: runId },
    select: { status: true, errorMessage: true, updatedAt: true },
  });
  if (!run) return null;

  const terminado = run.status === "completed" || run.status === "failed";
  const colgado = !terminado && Date.now() - run.updatedAt.getTime() > SIN_SEÑALES_MS;

  if (terminado) revalidatePath(`/agentes/ejecuciones/${runId}`);

  return {
    status: run.status,
    errorMessage: run.errorMessage,
    finished: terminado,
    stalled: colgado,
  };
}
