"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";

import { prisma } from "@/lib/db";
import { chunkTypes, type ChunkType } from "@/lib/estimator/contracts";
import { EstimatorError } from "@/lib/estimator/errors";
import { getCorpusStats, ingestDocument } from "@/lib/estimator/corpus";

export type FormState = { error: string | null };

/** Cuánto puede tardar un run en no dar señales antes de darlo por colgado. */
const SIN_SEÑALES_MS = 3 * 60_000;

/**
 * El JSON que pega la persona: un objeto o un array de objetos.
 *
 * Se valida que cada elemento sea un OBJETO. La app de referencia envuelve en
 * array cualquier JSON válido, así que `null` viaja como `[null]` y `123` como
 * `[123]`, y el servicio IA los rechaza con un 422 que llega sin contexto.
 */
function parseDocuments(raw: string): unknown[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(
      `El JSON no es válido: ${error instanceof Error ? error.message : "error de sintaxis"}`,
    );
  }
  const lista = Array.isArray(parsed) ? parsed : [parsed];
  if (lista.length === 0) {
    throw new Error("Pega al menos un documento (un objeto JSON o un array de objetos).");
  }
  const noSonObjetos = lista.filter(
    (d) => d === null || typeof d !== "object" || Array.isArray(d),
  );
  if (noSonObjetos.length > 0) {
    throw new Error(
      `Cada documento tiene que ser un objeto JSON. ${noSonObjetos.length} de ${lista.length} no lo son.`,
    );
  }
  return lista;
}

/**
 * La identidad del documento para el servicio IA.
 *
 * `source_path` es su clave de deduplicación, así que TIENE que derivarse del
 * documento y no del run: si llevara el id del run, el mismo presupuesto enviado
 * dos veces entraría dos veces, y la pantalla promete justo lo contrario. Es la
 * misma convención que usan los scripts de siembra (`data/…::<budget_id>`).
 *
 * Sin `budget_id` no hay identidad estable que usar, así que se cae al índice
 * dentro del lote: ese documento se podrá duplicar, y es mejor que rechazarlo.
 */
function sourcePathDe(documento: unknown, indice: number): string {
  const id = (documento as { budget_id?: unknown })?.budget_id;
  return typeof id === "string" && id.trim().length > 0
    ? `corpus-ui::${id.trim()}`
    : `corpus-ui::sin-id#${indice}`;
}

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

export async function startIndexRun(
  _previous: FormState,
  formData: FormData,
): Promise<FormState> {
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
  const colgado =
    !terminado && Date.now() - run.updatedAt.getTime() > SIN_SEÑALES_MS;

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
