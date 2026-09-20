"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { prisma } from "@/lib/db";
import { chunkTypes, type ChunkType } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { getCorpusStats, ingestDocument } from "@/lib/estimator/corpus";
import { parseDocuments, sourcePathDe } from "./parse";

export type FormState = { error: string | null };

/** Cuánto puede tardar un run en no dar señales antes de darlo por colgado. */
const SIN_SEÑALES_MS = 3 * 60_000;

/**
 * Indexa el lote documento a documento, en segundo plano.
 *
 * Sin `await` desde la acción: la persona va al detalle y ve el progreso. Esto
 * vive en el proceso de Node, que es de larga vida (`next start`), pero un
 * reinicio a mitad deja la fila en `running` para siempre — por eso el detalle
 * detecta un run sin señales en vez de fingir que sigue vivo.
 */
async function procesarLote(runId: string, documentos: unknown[], chunkType: ChunkType) {
  await prisma.indexRun.update({ where: { id: runId }, data: { status: "running" } });

  let procesados = 0;
  let saltados = 0;
  let chunks = 0;

  for (const [indice, documento] of documentos.entries()) {
    try {
      const respuesta = await ingestDocument({
        document: documento,
        chunkType,
        sourcePath: sourcePathDe(documento, indice),
      });
      chunks += respuesta.chunks_created;
    } catch (error) {
      // 409 = el servicio ya lo tenía. No es un fallo del lote.
      if (error instanceof EstimatorError && error.status === 409) {
        saltados += 1;
      } else {
        await prisma.indexRun.update({
          where: { id: runId },
          data: {
            status: "failed",
            processedCount: procesados,
            skippedCount: saltados,
            chunksCreated: chunks,
            errorMessage:
              error instanceof Error
                ? `Documento ${indice + 1} de ${documentos.length}: ${error.message}`
                : "Error desconocido durante la indexación.",
          },
        });
        return;
      }
    }
    procesados += 1;
    await prisma.indexRun.update({
      where: { id: runId },
      data: { processedCount: procesados, skippedCount: saltados, chunksCreated: chunks },
    });
  }

  // La foto de después se pide UNA vez, al terminar, y se congela.
  let despues = null;
  try {
    despues = await getCorpusStats();
  } catch {
    // El lote sí terminó: no tener la foto final no lo convierte en un fallo.
  }

  await prisma.indexRun.update({
    where: { id: runId },
    data: { status: "completed", afterStats: despues ?? undefined },
  });
}

export async function startIndexRun(_previous: FormState, formData: FormData): Promise<FormState> {
  const raw = String(formData.get("documents") ?? "").trim();
  const rawChunkType = String(formData.get("chunk_type") ?? "");
  const chunkType = (chunkTypes as readonly string[]).includes(rawChunkType)
    ? (rawChunkType as ChunkType)
    : "budget_component";

  let documentos: unknown[];
  try {
    documentos = parseDocuments(raw);
  } catch (error) {
    return { error: error instanceof Error ? error.message : "JSON inválido." };
  }

  // La foto de ANTES se pide antes de tocar nada: después ya no existiría.
  let antes = null;
  try {
    antes = await getCorpusStats();
  } catch (error) {
    if (error instanceof EstimatorError) return { error: error.userMessage };
    throw error;
  }

  const run = await prisma.indexRun.create({
    data: {
      chunkType,
      documentsJson: raw,
      submittedCount: documentos.length,
      beforeStats: antes,
    },
  });

  void procesarLote(run.id, documentos, chunkType);

  redirect(`/corpus/${run.id}`);
}

/** Lo que consulta el sondeo del detalle. Sólo LEE: un GET no escribe. */
export async function pollIndexRun(runId: string) {
  const run = await prisma.indexRun.findUnique({
    where: { id: runId },
    select: {
      status: true,
      processedCount: true,
      skippedCount: true,
      submittedCount: true,
      chunksCreated: true,
      errorMessage: true,
      updatedAt: true,
    },
  });
  if (!run) return null;

  const terminado = run.status === "completed" || run.status === "failed";
  // Un reinicio del contenedor a mitad de lote deja la fila en `running` sin
  // nadie que la mueva. Decirlo es mejor que sondear para siempre.
  const colgado = !terminado && Date.now() - run.updatedAt.getTime() > SIN_SEÑALES_MS;

  if (terminado) revalidatePath(`/corpus/${runId}`);

  return {
    status: run.status,
    processed: run.processedCount,
    skipped: run.skippedCount,
    submitted: run.submittedCount,
    chunksCreated: run.chunksCreated,
    errorMessage: run.errorMessage,
    finished: terminado,
    stalled: colgado,
  };
}
